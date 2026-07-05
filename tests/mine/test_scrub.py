from groundloop.mine.scrub import build_owner_tokens, scrub, leakage_flags, admit, parse_patch


def _oracle_gpuimage():
    return {
        "owning_repo": "android-gpuimage-plus",
        "owner_namespaces": ["org.wysaid"],
        "owner_slugs": ["wysaid", "android-gpuimage-plus", "gpuimage"],
        "owner_sonames": ["libCGE.so"],
        "expected_files": ["library/src/main/jni/interface/cgeImageHandlerAndroid.cpp"],
        "fix_patch": "@@\n-int old = 0;\n+long nativeCreateHandler() { return newImpl(); }\n",
    }


def test_parse_patch_extracts_added_methods_and_lines():
    p = parse_patch("@@\n-old\n+long nativeCreateHandler() { return x; }\n")
    assert "nativeCreateHandler" in p["methods"] or "nativeCreateHandler" in p["symbols"]
    assert any("nativeCreateHandler" in ln for ln in p["added_lines"])


def test_scrub_redacts_owner_namespace_class_and_method():
    tok = build_owner_tokens(_oracle_gpuimage())
    text = ("java.lang.UnsatisfiedLinkError: No implementation found for "
            "org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler()\n"
            "  at org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler(Native Method)")
    out = scrub(text, tok)
    assert "org.wysaid" not in out
    assert "CGEImageHandler" not in out
    assert "nativeCreateHandler" not in out
    # generic framework signal is KEPT
    assert "UnsatisfiedLinkError" in out


def test_generic_framework_tokens_survive():
    tok = build_owner_tokens(_oracle_gpuimage())
    text = "at android.opengl.GLSurfaceView.run() threw java.lang.UnsatisfiedLinkError; libffmpeg.so loaded"
    out = scrub(text, tok)
    assert "android.opengl.GLSurfaceView" in out
    assert "UnsatisfiedLinkError" in out
    assert "libffmpeg.so" in out  # ffmpeg is generic (GENERIC_SO_KEEP), not owner-unique


def test_scrub_redacts_stack_frame_source_file_suffix():
    tok = build_owner_tokens(_oracle_gpuimage())
    # realistic frame with the (File.java:line) suffix — the leak vector
    text = ("java.lang.UnsatisfiedLinkError\n"
            "  at org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler(CGEImageHandler.java:87)\n"
            "  at android.opengl.GLSurfaceView.run(GLSurfaceView.java:1540)")
    out = scrub(text, tok)
    assert "CGEImageHandler" not in out          # owner class no longer leaks via the suffix
    assert ".java:87" not in out
    assert "UnsatisfiedLinkError" in out          # generic exception kept
    # a KEPT generic frame: its body survives, only the file:line suffix is normalized
    assert "android.opengl.GLSurfaceView" in out
    assert "GLSurfaceView.java:1540" not in out


def test_media3_namespace_is_owner_for_media3_but_kept_for_newpipe():
    media3_tok = build_owner_tokens({
        "owning_repo": "media3", "owner_namespaces": ["androidx.media3"],
        "owner_slugs": ["media3"], "owner_sonames": [], "expected_files": [], "fix_patch": "",
    })
    text = "at androidx.media3.exoplayer.ExoPlayerImpl.release()"
    assert "androidx.media3" not in scrub(text, media3_tok)          # redacted for a media3 case
    # a newpipe case does NOT put androidx.media3 in owner tokens -> it survives
    newpipe_tok = build_owner_tokens({
        "owning_repo": "newpipe", "owner_namespaces": ["org.schabi.newpipe"],
        "owner_slugs": ["newpipe"], "owner_sonames": [], "expected_files": [], "fix_patch": "",
    })
    assert "androidx.media3" in scrub(text, newpipe_tok)


def test_leakage_flags_reject_when_owner_token_survives_then_admit_when_clean():
    tok = build_owner_tokens(_oracle_gpuimage())
    dirty = "at org.wysaid.nativePort.CGEImageHandler.nativeCreateHandler(Native Method)"
    flags, sig = leakage_flags(dirty, [dirty], tok, "android-gpuimage-plus")
    assert any(flags.values())
    assert admit(flags, sig) == "REJECT"

    clean_desc = "The app throws UnsatisfiedLinkError on start."
    clean_log = "java.lang.UnsatisfiedLinkError: No implementation found"
    flags2, sig2 = leakage_flags(clean_desc, [clean_log], tok, "android-gpuimage-plus")
    assert not any(flags2.values())
    assert admit(flags2, sig2) == "ADMIT"

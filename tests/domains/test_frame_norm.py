from groundloop.domains.android_ivi.frame_norm import normalize_java, normalize_native


def test_java_basic_key_and_package():
    f = normalize_java("org.schabi.newpipe.streams.SrtWriter", "write")
    assert f.package == "org.schabi.newpipe.streams"
    assert f.klass == "SrtWriter" and f.method == "write"
    assert f.key() == "org.schabi.newpipe.streams.SrtWriter.write"
    assert f.package_key() == "org.schabi.newpipe.streams"
    assert f.obfuscated is False


def test_java_no_package():
    f = normalize_java("CGEImageHandler", "process")
    assert f.package == "" and f.key() == "CGEImageHandler.process"


def test_java_strips_lambda_and_synthetic():
    assert normalize_java("com.x.Foo$$Lambda$3", "run").klass == "Foo"
    assert normalize_java("com.x.Foo$1", "onClick").klass == "Foo"
    assert normalize_java("com.x.Foo", "access$100").method == "access"


def test_java_inner_class_keeps_outer_package():
    f = normalize_java("com.x.Outer$Inner", "m")
    assert f.package == "com.x"          # package is the outer package
    assert f.klass == "Outer$Inner"      # inner class retained (only $$Lambda$N / $<digit> are stripped)


def test_java_jni_decode():
    f = normalize_java("Java_com_aaos_NativeBridge_nativeInit", "")
    assert f.package == "com.aaos" and f.klass == "NativeBridge" and f.method == "nativeInit"


def test_java_obfuscated_flagged():
    assert normalize_java("a.b.c", "d").obfuscated is True


def test_native_basename_and_offset_strip():
    f = normalize_native("/system/lib64/liboboe.so.1.2", "AudioStreamAAudio::requestStart+0x1c")
    assert f.soname == "liboboe.so"
    assert f.klass == "AudioStreamAAudio" and f.method == "requestStart"
    assert f.key() == "AudioStreamAAudio::requestStart"
    assert f.package_key() == "liboboe.so"


def test_native_bare_symbol():
    f = normalize_native("libdlt.so", "dlt_user_log_write_start")
    assert f.klass == "" and f.method == "dlt_user_log_write_start"
    assert f.key() == "dlt_user_log_write_start"

"""Per-case, oracle-parameterized leak-scrubber + leakage post-check (docs/type2-evaluation.md §4.3).

Redacts OWNER-identifying tokens (namespace/class/method/.so/slug/patch) while keeping generic
framework signal, then re-runs the real matcher's extractor to prove no owner-unique token survives.
"""
from __future__ import annotations

import re

GENERIC_SO_KEEP = {
    "libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so", "libart.so", "libbinder.so",
    "libEGL.so", "libGLESv1_CM.so", "libGLESv2.so", "libGLESv3.so", "libvulkan.so", "libOpenSLES.so",
    "libaaudio.so", "libmediandk.so", "libnativehelper.so", "libjnigraphics.so", "libz.so",
    "libc++.so", "libstdc++.so", "libffmpeg.so",
}
GENERIC_IDENT_KEEP = {
    "onCreate", "onStart", "onResume", "run", "init", "main", "read", "write", "open", "close",
    "Activity", "Fragment", "Service", "View", "Handler", "Runnable",
}
MIN_SHINGLE = 24
_GENERIC_ORG = {"android", "androidx", "google", "com", "org", "io", "team", "app"}

_ADDED = re.compile(r"(?m)^\+(?!\+\+).*")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_DECL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")  # a name immediately followed by '(' = a method/decl
# A stack frame's (File.ext:line) suffix leaks the owner class name (File==Class); redact for
# ALL frames. Carries no cross-ticket matchable signal; leaves (Native Method)/(Unknown Source) intact.
_SRC_SUFFIX = re.compile(
    r"\([A-Za-z_$][\w$]*\.(?:java|kt|kts|scala|cpp|cc|cxx|c|h|hpp|mm|so):\d+\)")


def parse_patch(patch: str) -> dict:
    added = [m.group(0)[1:] for m in _ADDED.finditer(patch or "")]
    methods, symbols = set(), set()
    for ln in added:
        for m in _DECL.finditer(ln):
            methods.add(m.group(1))
        for m in _IDENT.finditer(ln):
            symbols.add(m.group(0))
    return {"classes": set(), "methods": methods, "symbols": symbols, "added_lines": added}


def _shingles(lines, ks=(1, 2, 3)):
    norm = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
    norm = [ln for ln in norm if ln and ln not in {"return null;", "}", "{", "});"} and not ln.startswith("import ")]
    out = set()
    for k in ks:
        for i in range(len(norm) - k + 1):
            out.add(" ".join(norm[i:i + k]))
    return out


def _ns_variants(ns: str) -> re.Pattern:
    dot, slash = re.escape(ns), re.escape(ns.replace(".", "/"))
    tail = r"(?:[./][A-Za-z_$][\w$]*)*"
    return re.compile(rf"\bL?(?:{dot}|{slash}){tail};?")


def build_owner_tokens(oracle: dict) -> dict:
    fix = parse_patch(oracle.get("fix_patch", ""))
    exp = list(oracle.get("expected_files", []))
    bases = {f.rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in exp}
    repo = set(oracle.get("owner_slugs", []))
    gh_slug = oracle.get("owner_github_slug", "")
    if gh_slug and "/" in gh_slug:
        org = gh_slug.split("/", 1)[0]
        if org and org.lower() not in _GENERIC_ORG:
            repo.add(org)   # discriminative org (e.g. TeamNewPipe); the name-part is either already
                            # in owner_slugs or a generic word (e.g. 'media') — never redact it
    return {
        "REPO": repo,
        "PKG": set(oracle.get("owner_namespaces", [])),
        "PATH": set(exp) | bases,
        "CLASS": set(fix["classes"]),
        "METHOD": set(fix["methods"]) | set(fix["symbols"]),
        "SO": {s for s in oracle.get("owner_sonames", []) if s not in GENERIC_SO_KEEP},
        "PATCH": {sh for sh in _shingles(fix["added_lines"]) if len(sh) >= MIN_SHINGLE},
    }


def scrub(text: str, tok: dict) -> str:
    for ns in sorted(tok["PKG"], key=len, reverse=True):
        text = _ns_variants(ns).sub("<REDACTED_PKG>", text)
    text = _SRC_SUFFIX.sub("(<REDACTED_SRC>)", text)
    for so in sorted(tok["SO"], key=len, reverse=True):
        stem = so[:-3] if so.endswith(".so") else so
        text = re.compile(rf"\b{re.escape(so)}\b|\b{re.escape(stem)}\b", re.I).sub("<REDACTED_SO>", text)
    for p in sorted(tok["PATH"], key=len, reverse=True):
        text = re.compile(rf"\b{re.escape(p)}\b").sub("<REDACTED_PATH>", text)
    for c in sorted(tok["CLASS"], key=len, reverse=True):
        if len(c) >= 4 and c not in GENERIC_IDENT_KEEP and (c != c.lower() or any(ch.isdigit() for ch in c)):
            text = re.compile(rf"\b{re.escape(c)}\b").sub("<REDACTED_CLASS>", text)
    for mth in sorted(tok["METHOD"], key=len, reverse=True):
        if len(mth) >= 4 and mth not in GENERIC_IDENT_KEEP and (mth != mth.lower() or len(mth) >= 8):
            text = re.compile(rf"\b{re.escape(mth)}\b").sub("<REDACTED_METHOD>", text)
    for slug in sorted(tok["REPO"], key=len, reverse=True):
        text = re.compile(rf"\b{re.escape(slug)}\b", re.I).sub("<REDACTED_REPO>", text)
    for sh in sorted(tok["PATCH"], key=len, reverse=True):
        text = text.replace(sh, "<REDACTED_PATCH>")
    return text


def leakage_flags(sanitized_desc: str, sanitized_logs: list[str], tok: dict, owning_repo: str):
    from groundloop.core.types import LogAttachment, Ticket
    from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor

    text = sanitized_desc + "\n" + "\n".join(sanitized_logs)
    repo_alt = "|".join(re.escape(s) for s in (tok["REPO"] | {owning_repo}))
    flags = {
        "reponame_in_text": bool(re.search(rf"(?i)\b(?:{repo_alt})\b", text)) if repo_alt else False,
        "package_in_text": any(_ns_variants(ns).search(text) for ns in tok["PKG"]),
        "file_in_text": any(re.search(rf"\b{re.escape(p)}\b", text) for p in tok["PATH"]),
        "class_in_text": any(re.search(rf"\b{re.escape(c)}\b", text) for c in tok["CLASS"]),
        "so_in_text": any(re.search(rf"(?i)\b{re.escape(s[:-3] if s.endswith('.so') else s)}\b", text)
                          for s in tok["SO"]),
        "patch_in_text": any(sh in text for sh in tok["PATCH"]),
    }
    tk = Ticket(id="x", summary="", description=sanitized_desc)
    atts = tuple(LogAttachment(path=f"logs/{i}.txt", kind="other", content=b)
                 for i, b in enumerate(sanitized_logs))
    sig = AndroidSignalExtractor().extract(atts, tk)
    owner_all = (tok["REPO"] | tok["PKG"] | tok["CLASS"] | tok["METHOD"]
                 | {s[:-3] for s in tok["SO"]} | {owning_repo})
    flags["extractor_leak"] = any(
        any(o == t or o in t.replace("/", ".") for o in owner_all) for t in sig.tokens())
    return flags, sig


def admit(flags: dict, sig) -> str:
    if any(flags.values()):
        return "REJECT"
    generic = [t for group in (sig.errors, sig.libraries, sig.classes) for t in group]
    return "ADMIT" if generic else "BUCKET_PROSE_ONLY"

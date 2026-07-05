"""Split a markdown issue body into sanitized prose + typed log blocks (docs/type2-evaluation.md §4)."""
from __future__ import annotations

import re

RE_FENCE = re.compile(r"(?ms)^[ \t]*```[^\n]*\n(.*?)^[ \t]*```[ \t]*$")

RE_JAVA_FRAME = re.compile(r"(?m)^\s*at\s+[\w$.]+\.[\w$<>]+\(")
RE_EXC_HEADER = re.compile(r"(?m)^\s*(?:Caused by:\s*)?(?:[a-z][\w$]*\.)+[A-Z]\w*(?:Exception|Error)\b")
RE_LOGCAT_TAG = re.compile(r"(?m)^\s*[VDIWEF]/[\w$.\-]+\s*(?:\(\s*\d+\))?\s*:")
RE_LOGCAT_TS = re.compile(r"(?m)^\s*\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+\s+[VDIWEF]\s")
RE_FATAL = re.compile(r"\bFATAL EXCEPTION\b")
RE_ANDROIDRT = re.compile(r"\bE/AndroidRuntime\b")
RE_NAT_FRAME = re.compile(r"(?m)^\s*#\d{2}\s+pc\s+[0-9a-fA-F]+\b")
RE_NAT_SIG = re.compile(r"\bsignal\s+\d+\s+\(SIG[A-Z]+\)")
RE_NAT_BT = re.compile(r"(?m)^\s*backtrace:\s*$|\bAbort message\b|\bBuild fingerprint\b")
RE_ANR = re.compile(r"\bANR in\b|Input dispatching timed out")
RE_TEMPLATE = re.compile(r"(?m)^\s*(?:#{1,6}\s.*|-\s*\[[ xX]\].*|<!--.*?-->)\s*$")

_LOG_LINE = (RE_JAVA_FRAME, RE_LOGCAT_TAG, RE_LOGCAT_TS, RE_NAT_FRAME)


def classify(block: str) -> str:
    if RE_NAT_FRAME.search(block) or RE_NAT_SIG.search(block) or RE_NAT_BT.search(block):
        return "native"
    if RE_ANR.search(block):
        return "anr"
    if (RE_LOGCAT_TAG.search(block) or RE_LOGCAT_TS.search(block)
            or RE_ANDROIDRT.search(block) or RE_FATAL.search(block)):
        return "logcat"
    if RE_JAVA_FRAME.search(block) or RE_EXC_HEADER.search(block):
        return "stacktrace"
    return "other"


def _looks_like_log(block: str) -> bool:
    return classify(block) != "other" or bool(RE_JAVA_FRAME.search(block))


def split_issue_body(md: str) -> tuple[str, list[dict]]:
    """Return (sanitized prose, [{kind, text}]). Fenced + unfenced log runs become logs; the rest is prose."""
    logs: list[dict] = []
    spans: list[tuple[int, int]] = []
    for m in RE_FENCE.finditer(md):
        body = m.group(1)
        if _looks_like_log(body):
            logs.append({"kind": classify(body), "text": body.strip("\n")})
            spans.append(m.span())
    prose = _cut(md, spans)

    # Unfenced runs: >=3 consecutive log-looking lines (many issues paste raw logcat).
    prose, extra = _harvest_unfenced(prose)
    logs += extra
    prose = RE_TEMPLATE.sub("", prose)
    return prose.strip(), logs


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    out, prev = [], 0
    for a, b in sorted(spans):
        out.append(text[prev:a])
        prev = b
    out.append(text[prev:])
    return "".join(out)


def _harvest_unfenced(text: str) -> tuple[str, list[dict]]:
    lines = text.splitlines()
    keep: list[str] = []
    logs: list[dict] = []
    run: list[str] = []

    def flush_run():
        if len(run) >= 3:
            block = "\n".join(run)
            logs.append({"kind": classify(block), "text": block})
        else:
            keep.extend(run)
        run.clear()

    for ln in lines:
        if any(r.search(ln) for r in _LOG_LINE):
            run.append(ln)
        else:
            flush_run()
            keep.append(ln)
    flush_run()
    return "\n".join(keep), logs

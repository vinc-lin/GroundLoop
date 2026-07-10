"""Line-structured logcat parser (Android Log Match v2 §6.1). Supports threadtime and with-year formats;
unmatched lines are preserved as raw (pid=None). Pure; no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LINE = re.compile(
    r"^(?P<ts>(?:\d{4}-)?\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEFAS])\s+(?P<tag>[^:]+?):\s?(?P<msg>.*)$")


@dataclass(frozen=True)
class LogLine:
    ts: str | None
    pid: str | None
    tid: str | None
    level: str | None
    tag: str | None
    msg: str
    raw: str


def parse_logcat(text: str) -> list[LogLine]:
    out: list[LogLine] = []
    for raw in text.splitlines():
        m = _LINE.match(raw)
        if m:
            out.append(LogLine(ts=m["ts"], pid=m["pid"], tid=m["tid"], level=m["level"],
                               tag=m["tag"].strip(), msg=m["msg"], raw=raw))
        else:
            out.append(LogLine(ts=None, pid=None, tid=None, level=None, tag=None, msg=raw, raw=raw))
    return out

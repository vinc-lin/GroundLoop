from __future__ import annotations
import re
from typing import Sequence
from groundloop.core.types import LogAttachment, Ticket, Signals

_FRAME = re.compile(r"\bat\s+([a-zA-Z_][\w.]+)\.([A-Za-z_]\w*)\(")           # at pkg.Class.method(
_FQCLASS = re.compile(r"\b((?:[a-z][\w]*\.){2,}[A-Z]\w*)")                    # a.b.ClassName
_NATIVE = re.compile(r"#\d+\s+pc\s+[0-9a-fA-F]+\s+\S*?(lib\w+\.so)\s*\(([^)+]+)")
_SO = re.compile(r'(lib\w+\.so)')
_ERR = re.compile(r"\b([A-Z]\w+(?:Error|Exception))\b")


def _dedup(xs):
    seen: dict[str, None] = {}
    for x in xs:
        if x:
            seen.setdefault(x, None)
    return tuple(seen)


class AndroidSignalExtractor:
    """Parse Android logcat / Java stack traces / native backtraces into repo-discriminative signals."""

    def extract(self, logs: Sequence[LogAttachment], ticket: Ticket) -> Signals:
        text = "\n".join(a.content for a in logs) + "\n" + ticket.description
        classes, methods, packages, symbols, libs, errs = [], [], [], [], [], []
        for m in _FRAME.finditer(text):
            fq, meth = m.group(1), m.group(2)
            classes.append(fq)
            methods.append(meth)
            if "." in fq:
                packages.append(fq.rsplit(".", 1)[0])
        for m in _FQCLASS.finditer(text):
            classes.append(m.group(1))
            packages.append(m.group(1).rsplit(".", 1)[0])
        for m in _NATIVE.finditer(text):
            libs.append(m.group(1))
            symbols.append(m.group(2).strip())
        libs += _SO.findall(text)
        errs += _ERR.findall(text)
        return Signals(packages=_dedup(packages), classes=_dedup(classes), methods=_dedup(methods),
                       symbols=_dedup(symbols), libraries=_dedup(libs), errors=_dedup(errs))

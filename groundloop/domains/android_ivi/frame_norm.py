"""Deterministic frame normalization — the single comparison unit for fault extraction, routing, and the
fault_localization metric. Pure; no I/O. See spec Android Log Match v2 §6.2."""
from __future__ import annotations

import re
from dataclasses import dataclass

_LAMBDA = re.compile(r"\$\$Lambda\$\d+$")
_SYNTHETIC = re.compile(r"\$\d+$")              # anonymous inner class Foo$1
_OBFUSCATED_SEG = re.compile(r"^[a-z]$")        # single lowercase letter segment (R8/ProGuard)
_JNI = re.compile(r"^Java_(.+)_([A-Za-z_]\w*)$")


@dataclass(frozen=True)
class NormFrame:
    package: str
    klass: str
    method: str
    soname: str
    symbol: str
    obfuscated: bool
    raw: str

    def key(self) -> str:
        if self.soname or self.symbol:                      # native
            return f"{self.klass}::{self.method}" if self.klass else self.method
        base = f"{self.klass}.{self.method}" if self.method else self.klass
        return f"{self.package}.{base}" if self.package else base

    def package_key(self) -> str:
        return self.soname if self.soname else self.package


def _strip_class(cls: str) -> str:
    cls = _LAMBDA.sub("", cls)
    cls = _SYNTHETIC.sub("", cls)
    return cls


def normalize_java(fq_class: str, method: str, *, raw: str = "") -> NormFrame:
    """fq_class like 'a.b.Class' or 'a.b.Outer$Inner' or a JNI 'Java_a_b_Class_method'."""
    method = _SYNTHETIC.sub("", (method or "").strip())
    jni = _JNI.match(fq_class)
    if jni and not method:
        pkg_class = jni.group(1).replace("_", ".")
        method = jni.group(2)
        fq_class = pkg_class
    fq_class = fq_class.strip()
    if "." in fq_class:
        package, klass = fq_class.rsplit(".", 1)
    else:
        package, klass = "", fq_class
    klass = _strip_class(klass)
    # obfuscation: any package/class segment is a single lowercase letter
    segs = [s for s in (package.split(".") if package else []) + [klass] if s]
    obf = any(_OBFUSCATED_SEG.match(s) for s in segs)
    return NormFrame(package=package, klass=klass, method=method, soname="", symbol="",
                      obfuscated=obf, raw=raw or f"{fq_class}.{method}")


def normalize_native(so_path: str, symbol: str, *, raw: str = "") -> NormFrame:
    """so_path like '/system/lib64/libfoo.so.1.2'; symbol like 'Cls::method+0x1c' or 'func+164'."""
    base = so_path.rsplit("/", 1)[-1]
    m = re.match(r"(lib[\w.+-]*?\.so)", base)                # strip version suffix after .so
    soname = m.group(1) if m else base
    sym = re.split(r"\+0x|\+\d", symbol.strip())[0].strip()  # drop +offset
    if "::" in sym:
        klass, method = sym.rsplit("::", 1)
    else:
        klass, method = "", sym
    return NormFrame(package="", klass=klass, method=method, soname=soname, symbol=sym,
                      obfuscated=False, raw=raw or f"{soname} ({symbol})")

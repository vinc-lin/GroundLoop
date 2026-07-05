from groundloop.core.types import Signals
from groundloop.skills.ctx import SkillCtx


def build_panel() -> list[SkillCtx]:
    """A DISCRIMINATING ctx panel — each skill matches a proper, non-empty subset, so a mistranslated
    trigger flips a membership and fails parity. Selection sets (with the aligned fixtures):
    ctx0 -> {native}, ctx1 -> {native, jni}, ctx2 -> {jni}, ctx3 -> {}."""
    def c(text):
        return SkillCtx(signals=Signals(), repo="r", text=text.lower())
    return [
        c("java.lang.UnsatisfiedLinkError: couldn't find \"libffmpeg.so\""),   # native only
        c("crash at nativeCreateHandler (Native Method)"),                     # native (via 'native method') + jni
        c("registernatives failed for the handle"),                           # jni only
        c("live preview freezes; no crash; ui stops refreshing"),             # none
    ]

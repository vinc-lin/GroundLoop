"""KnowledgeInjectingFixEngine — composition-root FixEngine decorator that consults validated playbooks
and injects them into the inner fixer's prompt via with_preamble. run_ticket (frozen) passes only
(worktree, ticket, locations); the decorator reads the per-ticket signals from the shared
RecordingExtractor.last_signals (populated in run_ticket BEFORE propose). Fail-safe: no signals / empty
selection / a fixer without with_preamble (e.g. CannedFixEngine) -> the inner fixer runs unchanged."""
from groundloop.kb.inject import KnowledgeInjectingFixEngine
from groundloop.core.types import Patch, RepoRef, Ticket, WorkTree
from groundloop.kb.knowledge import KnowledgePlaybook


class _Fixer:
    def __init__(self, preamble=""):
        self.preamble = preamble
        self.model = None

    def with_preamble(self, p):
        return _Fixer(p)

    def propose(self, wt, ticket, locations):
        return Patch(diff=f"[{self.preamble}]", files=())


class _NoPreambleFixer:                       # e.g. CannedFixEngine — no with_preamble
    def __init__(self):
        self.model = None

    def propose(self, wt, ticket, locations):
        return Patch(diff="canned", files=())


class _Rec:                                   # stand-in RecordingExtractor
    def __init__(self, sig):
        self.last_signals = sig


class _Reg:
    def __init__(self, pbs):
        self.pbs = pbs

    def select(self, ctx, floor):
        return self.pbs


def _sig():
    from groundloop.core.types import Signals
    return Signals(errors=("NullPointerException",), methods=("onDestroyView",))


def _ticket():
    return Ticket(id="T-1", summary="crash", description="", logs=())


def _wt():
    return WorkTree(RepoRef("engineering"), "/w")


def _pb(pid="p", tier="validated"):
    return KnowledgePlaybook(id=pid, applies_when={"any_text": ["x"]}, signature="sig", localize=("l",),
                             fix=("f",), required_apis=("A.b",), grounding_refs=("A.b",), provenance="p",
                             tier=tier, evidence={})


def test_injects_selected_playbooks_via_with_preamble():
    dec = KnowledgeInjectingFixEngine(_Fixer(), registry=_Reg([_pb()]), extractor_rec=_Rec(_sig()),
                                      tier_floor="validated")
    assert "# Grounded playbooks" in dec.propose(_wt(), _ticket(), ["Main.kt"]).diff


def test_empty_selection_is_passthrough():
    dec = KnowledgeInjectingFixEngine(_Fixer(), registry=_Reg([]), extractor_rec=_Rec(_sig()),
                                      tier_floor="validated")
    assert dec.propose(_wt(), _ticket(), ["Main.kt"]).diff == "[]"     # no preamble -> inner unchanged


def test_no_signals_is_passthrough():
    dec = KnowledgeInjectingFixEngine(_Fixer(), registry=_Reg([_pb()]), extractor_rec=_Rec(None),
                                      tier_floor="validated")
    assert dec.propose(_wt(), _ticket(), ["Main.kt"]).diff == "[]"


def test_fixer_without_with_preamble_is_passthrough():
    dec = KnowledgeInjectingFixEngine(_NoPreambleFixer(), registry=_Reg([_pb()]), extractor_rec=_Rec(_sig()),
                                      tier_floor="validated")
    assert dec.propose(_wt(), _ticket(), ["Main.kt"]).diff == "canned"

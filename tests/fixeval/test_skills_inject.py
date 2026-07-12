"""--skills-inject: gate whether a skill arm perturbs the localize retrieval query.

`both` (default) = legacy: skills feed BOTH the localize query and the fix/plan prompt.
`fix-only` = skills feed ONLY the fix/plan prompt; localize stays byte-identical to `none`
(isolates the KB's fix-content value from retrieval pollution)."""
from groundloop.core.types import Patch, RepoRef, RepoScore, Signals, Ticket
from groundloop.fixeval.runner import FixEvalRunner
from groundloop.skills.base import Skill


def test_skill_inject_defaults_both():
    r = FixEvalRunner(issues=None, estate=None, catalog=[], tau_margin=1.0, tau_score=1.0)
    assert r.skill_inject == "both"
    r2 = FixEvalRunner(issues=None, estate=None, catalog=[], tau_margin=1.0, tau_score=1.0,
                       skills=object(), skill_inject="fix-only")
    assert r2.skill_inject == "fix-only"


# ---- behavioral: localize-invariance under fix-only ------------------------------------------------

class _Extractor:
    def extract(self, logs, ticket):
        return Signals(classes=("FooActivity",))


class _Index:
    """rank_repos -> a single high-scoring repo (decide predicts it); retrieve unused (localize patched)."""
    def rank_repos(self, signals, catalog):
        return [RepoScore(RepoRef("repoX"), 10.0)]

    def retrieve(self, ref, query):   # pragma: no cover - localize is monkeypatched
        return []


class _Estate:
    def materialize(self, ref):
        return type("WT", (), {"path": "/nonexistent/wt"})()


class _Skills:
    def select(self, ctx):
        return [Skill(id="s1", applies_to=lambda c: True,
                      guidance="Localize: bar\nFix: baz", signals=("foo",))]


class _Fixer:
    model = type("M", (), {"cost_usd": 0.0})()

    def __init__(self):
        self.preamble = None

    def with_preamble(self, pre):
        self.preamble = pre
        return self

    def propose(self, wt, ticket, locations):   # pragma: no cover - localize abstains first
        return Patch(diff="", files=())


class _Arm:
    name = "test"
    tau_margin = None
    tau_score = None
    index = _Index()
    extractor = _Extractor()


def _drive(monkeypatch, inject):
    """Run one _one() with localize patched to capture skill_query, then abstain (return [])
    so with_preamble (which ran BEFORE localize) is exercised without needing real git apply."""
    captured = {}

    def fake_localize(index, repo, signals, summary="", *, k=5, skill_query=""):
        captured["skill_query"] = skill_query
        return []                      # localize-abstain: stops before propose/patch_applies

    monkeypatch.setattr("groundloop.fixeval.runner.localize", fake_localize)
    fixer = _Fixer()
    runner = FixEvalRunner(issues=None, estate=_Estate(), catalog=[RepoRef("repoX")],
                           tau_margin=1.0, tau_score=1.0, skills=_Skills(), skill_inject=inject)
    ticket = Ticket(id="c", summary="s", description="d", logs=())
    case = type("C", (), {"case_id": "c"})()
    runner._one(case, _Arm(), ticket, [RepoRef("repoX")], fixer)
    return captured["skill_query"], fixer.preamble


def test_fix_only_empties_localize_query_but_keeps_fix_preamble(monkeypatch):
    skill_query, preamble = _drive(monkeypatch, "fix-only")
    assert skill_query == ""                       # localize byte-identical to the `none` arm
    assert preamble and "s1" in preamble           # fix prompt STILL carries the skill


def test_both_feeds_the_localize_query(monkeypatch):
    skill_query, preamble = _drive(monkeypatch, "both")
    assert "foo" in skill_query and "bar" in skill_query   # signals + Localize: hint reach retrieval
    assert preamble and "s1" in preamble

from groundloop.adapters.index.labs.component_prior import ComponentPriorIndex
from groundloop.domains.android_ivi.component_affinity import ComponentAffinity
from groundloop.domains.android_ivi.component_signals import COMPONENT_MARK
from groundloop.core.types import RepoRef, RepoScore, Signals

CAT = [RepoRef("Core"), RepoRef("Integ"), RepoRef("Noise")]


class _Base:
    """Ranks by a fixed score map; strips nothing. Records the signals it was handed."""
    def __init__(self, scores):
        self.scores = scores
        self.seen = None

    def rank_repos(self, signals, catalog):
        self.seen = signals
        return sorted((RepoScore(r, self.scores.get(r.name, 0.0)) for r in catalog),
                      key=lambda s: s.score, reverse=True)

    def retrieve(self, repo, query):
        return ["f"]


def _sig(component):
    return Signals(errors=(COMPONENT_MARK + component,)) if component else Signals()


def test_prior_boosts_component_repo_and_strips_marker():
    base = _Base({"Noise": 0.5, "Core": 0.1})            # base alone ranks Noise first
    aff = ComponentAffinity({"CarPlay": {"Core": 4, "Integ": 1}})
    idx = ComponentPriorIndex(base, aff, weight=1.0)
    ranked = idx.rank_repos(_sig("CarPlay"), CAT)
    assert ranked[0].repo.name == "Core"                 # prior overturns the size-biased base
    assert not any(e.startswith(COMPONENT_MARK) for e in base.seen.errors)  # base never saw the marker


def test_no_component_is_pure_base():
    base = _Base({"Noise": 1.0})
    idx = ComponentPriorIndex(base, ComponentAffinity({}), weight=1.0)
    assert idx.rank_repos(_sig(""), CAT)[0].repo.name == "Noise"


def test_prior_is_scale_invariant_to_base_magnitude():
    # a size-biased base ranks Noise far above Core by RAW magnitude; the prior must still win
    base = _Base({"Noise": 100.0, "Core": 1.0})
    aff = ComponentAffinity({"CarPlay": {"Core": 4, "Integ": 1}})
    ranked = ComponentPriorIndex(base, aff, weight=1.0).rank_repos(_sig("CarPlay"), CAT)
    assert ranked[0].repo.name == "Core"        # base magnitude 100 vs 1 does NOT swamp the prior


def test_retrieve_delegates():
    idx = ComponentPriorIndex(_Base({}), ComponentAffinity({}), weight=1.0)
    assert idx.retrieve(RepoRef("Core"), "q") == ["f"]

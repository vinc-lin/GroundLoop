from groundloop.core.workflow import run_ticket, RunRecord
from groundloop.core.types import (Ticket, Signals, RepoRef, RepoScore, WorkTree, Patch, Change)


class FIssues:
    def __init__(self): self.transitions = []
    def fetch(self, tid): return Ticket(tid, "crash", "d")
    def post_comment(self, tid, body): pass
    def transition(self, tid, status): self.transitions.append((tid, status))


class FExtract:
    def extract(self, logs, ticket): return Signals(classes=("org.wysaid.X",))


class FEstate:
    def catalog(self): return [RepoRef("android-gpuimage-plus"), RepoRef("organicmaps")]
    def materialize(self, repo): return WorkTree(repo, "/tmp/x")


class FIndex:
    def rank_repos(self, signals, catalog):
        return [RepoScore(RepoRef("android-gpuimage-plus"), 2.0), RepoScore(RepoRef("organicmaps"), 0.0)]
    def retrieve(self, repo, query): return ["cgeImageHandlerAndroid.cpp"]


class FFix:
    def propose(self, wt, ticket, locations): return Patch("diff", tuple(locations))


class FSink:
    def __init__(self): self.bound = []
    def submit(self, repo, patch, ticket): return Change("Iabc", f"[{ticket.id}]", ticket.id, patch)
    def bind(self, change, ticket): self.bound.append(change.change_id)


def test_run_ticket_end_to_end():
    issues, sink = FIssues(), FSink()
    rec = run_ticket("GP-352", issues=issues, extractor=FExtract(), estate=FEstate(),
                     index=FIndex(), fixer=FFix(), changes=sink)
    assert isinstance(rec, RunRecord)
    assert rec.chosen.name == "android-gpuimage-plus"          # MATCH picked the owner
    assert rec.locations == ["cgeImageHandlerAndroid.cpp"]
    assert rec.change.change_id == "Iabc" and rec.bound and sink.bound == ["Iabc"]

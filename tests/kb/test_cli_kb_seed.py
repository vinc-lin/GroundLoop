"""`gloop kb-seed` CLI (Task 11). Hermetic: builds a REAL tiny atlas Store indexing units that NAME the
`fragment-view-after-destroy-npe` feedstock playbook's hint_apis, so exactly that playbook grounds and is
admitted at tier=candidate — the other 11 feedstock skills' hint_apis are absent from the atlas and are
rejected (unresolved_refs). Exercises the real Store/FTS grounding path end-to-end via the CLI, not a
resolver stub."""
import groundloop.cli as cli
from groundloop.engines.atlas.store import Store, Unit
from groundloop.kb.knowledge import load_knowledge


def _real_store(tmp_path) -> Store:
    s = Store(str(tmp_path / "atlas.db"))
    units = [
        Unit(repo="engineering", kind="symbol", name="onDestroyView",
             qualified_name="Fragment.onDestroyView", file="F.kt", repo_head="h",
             text="fun onDestroyView()", meta={}),
        Unit(repo="engineering", kind="symbol", name="getViewLifecycleOwner",
             qualified_name="Fragment.getViewLifecycleOwner", file="F.kt", repo_head="h",
             text="fun getViewLifecycleOwner(): LifecycleOwner", meta={}),
        Unit(repo="engineering", kind="symbol", name="viewLifecycleOwner",
             qualified_name="Fragment.viewLifecycleOwner", file="F.kt", repo_head="h",
             text="val viewLifecycleOwner: LifecycleOwner", meta={}),
        Unit(repo="engineering", kind="symbol", name="getView",
             qualified_name="Fragment.getView", file="F.kt", repo_head="h",
             text="fun getView(): View?", meta={}),
    ]
    s.reindex_repo("engineering", list(zip(units, [[0.0]] * len(units))), repo_head="h")
    return s


def test_kb_seed_writes_grounded_candidate_store(tmp_path):
    _real_store(tmp_path)                              # writes atlas.db at tmp_path/atlas.db
    atlas = str(tmp_path / "atlas.db")
    out = str(tmp_path / "kb.json")

    rc = cli.main(["kb-seed", "--index-db", atlas, "--out", out])

    assert rc == 0
    store = load_knowledge(out)
    assert len(store) >= 1 and all(pb.tier == "candidate" for pb in store.values())
    # the ONLY skill whose hint_apis all resolve against this atlas is fragment-view-after-destroy-npe
    assert "fragment-view-after-destroy-npe" in store
    admitted = store["fragment-view-after-destroy-npe"]
    assert set(admitted.grounding_refs) == {
        "getViewLifecycleOwner", "onDestroyView", "viewLifecycleOwner", "getView"}
    # the other 11 feedstock skills cite APIs absent from this tiny atlas -> rejected, not admitted
    assert len(store) < 12


def test_kb_seed_prints_admitted_and_rejected_counts(tmp_path, capsys):
    _real_store(tmp_path)
    atlas = str(tmp_path / "atlas.db")
    out = str(tmp_path / "kb.json")

    rc = cli.main(["kb-seed", "--index-db", atlas, "--out", out])

    assert rc == 0
    output = capsys.readouterr().out
    assert "kb-seed:" in output and "admitted 1" in output and "rejected 11" in output and out in output

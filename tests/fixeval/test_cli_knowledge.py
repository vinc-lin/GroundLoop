"""`gloop fixeval --knowledge {none,candidate,validated}` composition-root wiring (Phase B3). Mirrors
tests/fixeval/test_cli_skills.py: hermetic (no live model / no live bge-m3). The run test proves all
three arms return 0; the _load_knowledge unit test pins the kind->(registry, tier_floor) mapping against a
monkeypatched tiny store (so it does not depend on the shipped knowledge.json)."""
import shutil
from pathlib import Path

from groundloop.cli import main
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture

FIX = Path(__file__).parent.parent / "fixtures"


def _ds(tmp_path):
    ds = tmp_path / "ds"
    ds.mkdir()
    shutil.copytree(FIX / "android_ivi" / "gpuimage-352", ds / "GP-352")
    return ds


def test_fixeval_knowledge_flag_runs_all_arms(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)   # hermetic canned model (no live fix)
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)    # no live bge-m3 rerank
    ds, db = _ds(tmp_path), build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    common = ["--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
              "--index-db", db, "--repos", str(FIX / "repos"), "--fixer", "plan"]
    assert main(["fixeval", *common, "--knowledge", "none", "--out", str(tmp_path / "none.json")]) == 0
    assert main(["fixeval", *common, "--knowledge", "candidate", "--out", str(tmp_path / "cand.json")]) == 0
    assert main(["fixeval", *common, "--knowledge", "validated", "--out", str(tmp_path / "val.json")]) == 0
    assert (tmp_path / "cand.json").is_file() and (tmp_path / "val.json").is_file()


def test_load_knowledge_maps_kind_to_registry_and_floor(monkeypatch):
    from groundloop.cli import _load_knowledge
    from groundloop.kb.knowledge import Knowledge
    from groundloop.kb.registry import KnowledgeRegistry

    fixture = {"c1": Knowledge(id="c1", applies_when={"any_text": ["x"]}, type="fix_step", content="c",
                               grounding_refs=(), provenance="p", tier="candidate", evidence={})}
    monkeypatch.setattr("groundloop.kb.registry.load_knowledge", lambda path=None: fixture)

    assert _load_knowledge("none", None) == (None, "validated")   # none -> no registry, prod floor
    reg_c, floor_c = _load_knowledge("candidate", None)
    assert isinstance(reg_c, KnowledgeRegistry) and floor_c == "candidate"   # EVAL floor
    assert len(reg_c.items) == 1                                 # actually loaded the (fixture) store
    reg_v, floor_v = _load_knowledge("validated", None)
    assert isinstance(reg_v, KnowledgeRegistry) and floor_v == "validated"  # PRODUCTION floor


def test_load_knowledge_reads_from_store_path_fixture(tmp_path):
    """--knowledge-store override: _load_knowledge(store_path=<fixture>) loads the FIXTURE store, not the
    packaged default (proves external/working knowledge stores work — the Phase D runbook requirement)."""
    from groundloop.cli import _load_knowledge
    from groundloop.kb.knowledge import Knowledge, save_knowledge
    from groundloop.kb.registry import KnowledgeRegistry

    store = tmp_path / "knowledge.json"
    save_knowledge(str(store), {"only": Knowledge(id="only", applies_when={"any_text": ["z"]}, type="fix_step",
                                                  content="from-the-fixture", grounding_refs=(), provenance="p",
                                                  tier="candidate", evidence={})})
    reg, floor = _load_knowledge("candidate", None, store_path=str(store))
    assert isinstance(reg, KnowledgeRegistry) and floor == "candidate"
    assert [k.id for k in reg.items] == ["only"]                # loaded the FIXTURE store...
    assert reg.items[0].content == "from-the-fixture"          # ...not the packaged knowledge.json


def test_fixeval_threads_knowledge_store_to_load_knowledge(tmp_path, monkeypatch):
    """`gloop fixeval --knowledge candidate --knowledge-store <fixture>` threads the override through to
    _load_knowledge as store_path (so the working store on ext4 is what the run reads)."""
    import groundloop.cli as cli
    from groundloop.kb.knowledge import Knowledge, save_knowledge

    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)    # hermetic canned model
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)     # no live bge-m3 rerank
    store = tmp_path / "knowledge.json"
    save_knowledge(str(store), {"fx": Knowledge(id="fx", applies_when={"any_text": ["z"]}, type="fix_step",
                                                content="fixture-only", grounding_refs=(), provenance="p",
                                                tier="candidate", evidence={})})

    seen: dict = {}
    real = cli._load_knowledge

    def spy(kind, embedder, store_path=None):
        seen["store_path"] = store_path
        return real(kind, embedder, store_path=store_path)

    monkeypatch.setattr(cli, "_load_knowledge", spy)

    ds, db = _ds(tmp_path), build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    rc = cli.main(["fixeval", "--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
                   "--index-db", db, "--repos", str(FIX / "repos"), "--fixer", "plan",
                   "--knowledge", "candidate", "--knowledge-store", str(store),
                   "--out", str(tmp_path / "out.json")])
    assert rc == 0
    assert seen["store_path"] == str(store)                       # the flag reached _load_knowledge

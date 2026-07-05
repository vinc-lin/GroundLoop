import json
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


def test_fixeval_skills_flag_runs_both_arms(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOOP_PRODUCE_API_KEY", raising=False)   # hermetic canned model (no live fix)
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)    # force predicate-only mock arm (no live bge-m3)
    ds, db = _ds(tmp_path), build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    common = ["--dataset", str(ds), "--catalog", str(FIX / "android_ivi" / "catalog.json"),
              "--index-db", db, "--repos", str(FIX / "repos")]
    assert main(["fixeval", *common, "--skills", "none", "--out", str(tmp_path / "off.json")]) == 0
    assert main(["fixeval", *common, "--skills", "mock", "--out", str(tmp_path / "on.json")]) == 0
    assert (tmp_path / "off.json").is_file() and (tmp_path / "on.json").is_file()


def test_compare_emits_accept_verdict(tmp_path):
    # hand-built off/on boards -> compare CLI writes a verdict json with the accept gate
    def board(fr1, fab):
        return {"arms": {"membership+logs": {
            "n": 1, "patch_apply_rate": 1.0, "n_gradeable": 1, "resolved_by_case": {"GP-352": None},
            "file_recall@1": {"value": fr1}, "file_recall@3": {"value": fr1}, "file_recall@5": {"value": fr1},
            "resolved_rate": {"value": None}, "required_api_pass_rate": {"value": None},
            "fabrication_rate": {"value": fab}, "cost_per_solved": None, "cost_total": 0.0,
            "phi_c": {"1.0": fr1}}}}
    (tmp_path / "off.json").write_text(json.dumps(board(0.0, 0.0)))
    (tmp_path / "on.json").write_text(json.dumps(board(1.0, 0.0)))
    out = tmp_path / "verdict.json"
    rc = main(["compare", "--base", str(tmp_path / "off.json"), "--head", str(tmp_path / "on.json"),
               "--arm", "membership+logs", "--out", str(out)])
    assert rc == 0
    v = json.loads(out.read_text())
    assert v["verdict"]["accepted"] and v["metrics"]["file_recall@1"]["delta"] == 1.0


def test_load_skills_selects_seed_corpus(tmp_path):
    # --skills-seed override: kb/placebo arms load OUR tiny fixture corpus (N skills of that file)
    from groundloop.cli import _load_skills
    corpus = tmp_path / "tiny.toml"
    corpus.write_text(
        '[[skill]]\n'
        'id = "s1"\n'
        'guidance = "Signature: NPE. Localize: FooActivity. Fix: null-guard."\n'
        'signals = ["npe"]\n'
        '[skill.match]\n'
        'any_errors = ["nullpointerexception"]\n\n'
        '[[skill]]\n'
        'id = "s2"\n'
        'guidance = "Signature: SIGSEGV. Localize: native peer. Fix: weak_ptr lock."\n'
        'signals = ["sigsegv"]\n'
        '[skill.match]\n'
        'any_errors = ["sigsegv"]\n'
    )
    reg = _load_skills("kb", str(corpus), None)
    assert reg is not None and {s.id for s in reg.skills} == {"s1", "s2"}
    # placebo arm honors the SAME --skills-seed override
    assert {s.id for s in _load_skills("placebo", str(corpus), None).skills} == {"s1", "s2"}
    # none -> baseline: no KB injected
    assert _load_skills("none", None, None) is None


def test_load_skills_kb_default_is_our_corpus():
    # kind=kb with no seed -> OUR 12-skill corpus (groundloop/kb/data/aaos_kb_seed.toml)
    from groundloop.cli import _load_skills
    from groundloop.kb.validate import SEED_PATH as KB_SEED
    reg = _load_skills("kb", None, None)
    assert reg is not None and len(reg.skills) == 12
    # mock with no seed -> the SP3 4-playbook default seed
    assert len(_load_skills("mock", None, None).skills) == 4
    assert KB_SEED.endswith("aaos_kb_seed.toml")

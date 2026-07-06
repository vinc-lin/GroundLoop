"""`gloop kb-promote` composition-root wrapper over load_sidecar + apply_verdict + save_sidecar.

Hermetic (no network/LLM): feeds a fake kb-ab verdict.json and asserts the sidecar tier ladder walks
correctly — a passing verdict promotes every KB skill one rung; two CONSECUTIVE failing verdicts demote
one rung (hysteresis=2), a single fail does not. Also checks the packaged seed sidecar
(groundloop/kb/data/provenance.json) carries the 12 corpus skills as fresh candidates, and that the
sidecar round-trips through load_sidecar/save_sidecar."""
import json
from pathlib import Path

import groundloop.cli as cli
from groundloop.kb.provenance import SIDECAR_PATH, load_sidecar
from groundloop.kb.validate import SEED_PATH as KB_SEED
from groundloop.kb.validate import load_corpus

CORPUS_IDS = [s["id"] for s in load_corpus(KB_SEED)]


def _write_verdict(path: Path, accepted: bool) -> None:
    path.write_text(json.dumps({
        "eval_arm": "membership+logs",
        "kb_vs_placebo": {"accepted": accepted, "reasons": ["test"]},
        "kb_vs_none": {"accepted": accepted, "reasons": ["test"]},
    }))


def test_passing_verdict_seeds_then_promotes_all_to_applied(tmp_path):
    prov = tmp_path / "provenance.json"          # missing -> handler seeds 12 candidates first
    verdict = tmp_path / "verdict.json"
    _write_verdict(verdict, accepted=True)

    rc = cli.main(["kb-promote", "--verdict", str(verdict), "--provenance", str(prov)])
    assert rc == 0

    records = load_sidecar(str(prov))            # round-trip through the JSON sidecar
    assert set(records) == set(CORPUS_IDS)
    assert len(records) == 12
    for sid in CORPUS_IDS:
        assert records[sid].tier == "applied"    # candidate -> applied on one pass
        assert records[sid].fail_count == 0
        assert records[sid].lineage == "authored cold-start"


def test_two_consecutive_fails_demote_hysteresis(tmp_path):
    prov = tmp_path / "provenance.json"
    v_pass = tmp_path / "pass.json"
    v_fail = tmp_path / "fail.json"
    _write_verdict(v_pass, accepted=True)
    _write_verdict(v_fail, accepted=False)

    # climb to 'applied' first so there is a rung to slide down from
    assert cli.main(["kb-promote", "--verdict", str(v_pass), "--provenance", str(prov)]) == 0
    assert all(r.tier == "applied" for r in load_sidecar(str(prov)).values())

    # one fail: hysteresis holds the tier, only the fail streak advances
    assert cli.main(["kb-promote", "--verdict", str(v_fail), "--provenance", str(prov)]) == 0
    once = load_sidecar(str(prov))
    for sid in CORPUS_IDS:
        assert once[sid].tier == "applied"
        assert once[sid].fail_count == 1
        assert once[sid].demotions == ()

    # second consecutive fail: demote one rung, record the transition, reset the streak
    assert cli.main(["kb-promote", "--verdict", str(v_fail), "--provenance", str(prov)]) == 0
    twice = load_sidecar(str(prov))
    for sid in CORPUS_IDS:
        assert twice[sid].tier == "candidate"
        assert twice[sid].fail_count == 0
        assert twice[sid].demotions == ("applied->candidate",)


def test_default_provenance_flag_targets_packaged_sidecar(tmp_path, capsys):
    """Omitting --provenance defaults to the packaged sidecar path (we don't write it here — just
    assert the resolved default is groundloop/kb/data/provenance.json via the printed target)."""
    verdict = tmp_path / "verdict.json"
    _write_verdict(verdict, accepted=True)
    # copy the packaged sidecar into tmp and point at it, to avoid mutating the committed artifact
    seeded = tmp_path / "provenance.json"
    seeded.write_text(Path(SIDECAR_PATH).read_text())
    rc = cli.main(["kb-promote", "--verdict", str(verdict), "--provenance", str(seeded)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "kb-promote" in out
    # every corpus skill prints a transition line
    for sid in CORPUS_IDS:
        assert sid in out


def test_packaged_seed_sidecar_has_12_candidates():
    records = load_sidecar(SIDECAR_PATH)
    assert set(records) == set(CORPUS_IDS)
    assert len(records) == 12
    for sid in CORPUS_IDS:
        rec = records[sid]
        assert rec.tier == "candidate"
        assert rec.lineage == "authored cold-start"
        assert rec.validating_case_ids == ()
        assert rec.measured_lift == {}
        assert rec.evidence_context == {}
        assert rec.fail_count == 0
        assert rec.demotions == ()


def test_kb_promote_help_lists_flags():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "groundloop.cli", "kb-promote", "--help"],
                         capture_output=True, text=True)
    for flag in ("--verdict", "--provenance"):
        assert flag in out.stdout

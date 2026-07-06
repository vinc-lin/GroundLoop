"""`gloop kb-distill` — the GATED Phase B/C harvest->distill->revalidate driver (composition root).

Hermetic (no network / no LLM / no atlas). Two seams are stubbed so the whole chain is deterministic:
  * `cli._build_distill_run_fn(args, candidate)` -> a scripted run_fn(guidance)->lift (no real A/B), and
  * `cli._case_split(case_id)` -> the split firewall (only calib/train cases may author a candidate).

Asserted behaviour:
  * a verdict whose kb_vs_placebo is NOT accepted -> handler returns 0 and touches nothing (the gate);
  * an accepted verdict on a tiny fixture -> only the LOAD-BEARING (lofo) + RE-VALIDATED fragments
    re-enter a distilled corpus and earn an apply_verdict tier bump in the provenance sidecar;
  * a revalidate==False candidate promotes nothing (no corpus change);
  * an eval/holdout-split dataset authors nothing (the firewall).
"""
import json
import shutil
from pathlib import Path

import groundloop.cli as cli
from groundloop.kb.validate import load_corpus

FIX = Path(__file__).parent.parent / "fixtures" / "android_ivi" / "gpuimage-352"


def _make_dataset(tmp_path) -> Path:
    """Two crash cases sharing the UnsatisfiedLinkError signature (one cluster)."""
    ds = tmp_path / "ds"
    ds.mkdir()
    for cid in ("case-a", "case-b"):
        shutil.copytree(FIX, ds / cid)
        # keep the loop-visible ticket id unique per case (MockJira reads it back)
        tj = ds / cid / "ticket.json"
        raw = json.loads(tj.read_text())
        raw["id"] = cid
        tj.write_text(json.dumps(raw))
    (ds / "catalog.json").write_text(json.dumps([{"name": "android-gpuimage-plus"}]))
    return ds


def _write_verdict(path: Path, accepted: bool) -> None:
    path.write_text(json.dumps({
        "eval_arm": "membership+logs",
        "kb_vs_placebo": {"accepted": accepted, "reasons": ["test"]},
        "kb_vs_none": {"accepted": accepted, "reasons": ["test"]},
    }))


def _args(ds, prov, verdict):
    return ["kb-distill", "--verdict", str(verdict), "--dataset", str(ds),
            "--index-db", str(ds / "atlas.db"), "--repos", str(ds),
            "--provenance", str(prov)]


# --------------------------------------------------------------------------- the gate

def test_not_accepted_skips_and_touches_nothing(tmp_path, monkeypatch, capsys):
    ds = _make_dataset(tmp_path)
    prov = tmp_path / "provenance.json"
    distilled = tmp_path / "distilled.toml"
    verdict = tmp_path / "verdict.json"
    _write_verdict(verdict, accepted=False)

    # if the driver ever reached the chain these would blow up loudly
    def _boom(*a, **k):
        raise AssertionError("gate breached: chain ran on a non-accepted verdict")
    monkeypatch.setattr(cli, "_build_distill_run_fn", _boom)

    rc = cli.main(_args(ds, prov, verdict))
    assert rc == 0
    assert not prov.exists()          # no provenance sidecar written
    assert not distilled.exists()     # no distilled corpus written
    assert "Phase-A not passed" in capsys.readouterr().out


# --------------------------------------------------------------------------- promotion

def _pass_stub(g: str) -> float:
    """Signature line is inert (removing it holds the lift); Localize+Fix are each load-bearing."""
    has_loc, has_fix = "Localize:" in g, "Fix:" in g
    if has_loc and has_fix:
        return 2.0
    if has_loc or has_fix:
        return 1.0
    return 0.0


def test_accepted_promotes_only_load_bearing_revalidated_fragments(tmp_path, monkeypatch, capsys):
    ds = _make_dataset(tmp_path)
    prov = tmp_path / "provenance.json"
    distilled = tmp_path / "distilled.toml"
    verdict = tmp_path / "verdict.json"
    _write_verdict(verdict, accepted=True)

    monkeypatch.setattr(cli, "_case_split", lambda cid: "train")
    monkeypatch.setattr(cli, "_build_distill_run_fn", lambda args, candidate: _pass_stub)

    rc = cli.main(_args(ds, prov, verdict))
    assert rc == 0

    # the distilled corpus re-entered with ONE skill carrying only the load-bearing fragments
    assert distilled.is_file()
    skills = load_corpus(str(distilled))
    assert len(skills) == 1
    sk = skills[0]
    assert sk["id"] == "harvest-unsatisfiedlinkerror"
    assert "Localize:" in sk["guidance"] and "Fix:" in sk["guidance"]
    assert "Signature:" not in sk["guidance"]     # the inert fragment was pruned by lofo

    # the promoted skill earned a tier bump in the provenance sidecar (candidate -> applied)
    from groundloop.kb.provenance import load_sidecar
    records = load_sidecar(str(prov))
    assert set(records) == {"harvest-unsatisfiedlinkerror"}
    assert records["harvest-unsatisfiedlinkerror"].tier == "applied"

    assert "harvest-unsatisfiedlinkerror" in capsys.readouterr().out


def _fail_stub(g: str) -> float:
    """Localize is essential; Signature+Fix are individually inert but jointly load-bearing, so lofo
    keeps only [Localize] and the pruned form under-performs the form-A baseline -> revalidate False."""
    has_sig, has_loc, has_fix = "Signature:" in g, "Localize:" in g, "Fix:" in g
    if not has_loc:
        return 0.0
    extra = int(has_sig) + int(has_fix)
    if extra >= 1:
        return 1.0
    return 0.7


def test_accepted_but_revalidate_false_promotes_nothing(tmp_path, monkeypatch):
    ds = _make_dataset(tmp_path)
    prov = tmp_path / "provenance.json"
    distilled = tmp_path / "distilled.toml"
    verdict = tmp_path / "verdict.json"
    _write_verdict(verdict, accepted=True)

    monkeypatch.setattr(cli, "_case_split", lambda cid: "train")
    monkeypatch.setattr(cli, "_build_distill_run_fn", lambda args, candidate: _fail_stub)

    rc = cli.main(_args(ds, prov, verdict))
    assert rc == 0
    assert not distilled.exists()     # distilled form failed re-validation -> not canonical
    assert not prov.exists()          # nothing earned a tier bump


def test_eval_split_authors_nothing_firewall(tmp_path, monkeypatch):
    ds = _make_dataset(tmp_path)
    prov = tmp_path / "provenance.json"
    distilled = tmp_path / "distilled.toml"
    verdict = tmp_path / "verdict.json"
    _write_verdict(verdict, accepted=True)

    # every case lands in eval -> the split firewall bars authorship even on a PASSing run_fn
    monkeypatch.setattr(cli, "_case_split", lambda cid: "eval")
    monkeypatch.setattr(cli, "_build_distill_run_fn", lambda args, candidate: _pass_stub)

    rc = cli.main(_args(ds, prov, verdict))
    assert rc == 0
    assert not distilled.exists()
    assert not prov.exists()


def test_kb_distill_help_lists_flags():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "groundloop.cli", "kb-distill", "--help"],
                         capture_output=True, text=True)
    for flag in ("--verdict", "--dataset", "--index-db", "--repos", "--provenance"):
        assert flag in out.stdout

"""`gloop kb-attribute` driver (Phase C4). Hermetic: GATED on a plan archive (no plans/ -> exit 0 before any
spend); the fix-eval seam cli._build_attribute_run_card_fn is monkeypatched to a scripted run_card_fn (no
atlas / no model), so the real load_archive -> screen_knowledge -> attribute_and_govern -> save_knowledge
path runs end-to-end over fixture knowledge.json + a fixture archive."""
import json

import groundloop.cli as cli
from groundloop.kb.knowledge import Knowledge, load_knowledge, save_knowledge


def _payload(case, fired, groundedness):
    return {"schema": 1, "case_id": case, "arm": "membership+logs", "predicted_repo": "r",
            "plan": {"steps": []}, "fired_skills": [], "fired_knowledge": list(fired),
            "outcome": {"groundedness": groundedness, "replans": 0, "abstained": False,
                        "patch_emitted": True, "patch_applies": True}}


def test_kb_attribute_gated_on_archive(tmp_path, capsys):
    rc = cli.main(["kb-attribute", "--archive", str(tmp_path / "plans"), "--dataset", str(tmp_path),
                   "--index-db", "unused.db", "--repos", str(tmp_path)])
    assert rc == 0                                          # exits cleanly with NO archive present
    assert "no plan archive" in capsys.readouterr().out


def test_kb_attribute_promotes_via_seam(tmp_path, monkeypatch):
    store = tmp_path / "knowledge.json"
    save_knowledge(str(store), {"c1": Knowledge(id="c1", applies_when={"any_text": ["x"]}, type="fix_step",
                                                content="advice", grounding_refs=("GetLongField",),
                                                provenance="p", tier="candidate", evidence={})})
    d = tmp_path / "plans"
    d.mkdir()
    (d / "a__arm.json").write_text(json.dumps(_payload("a", ["c1"], 0.9)))    # c1 fired, high groundedness
    (d / "b__arm.json").write_text(json.dumps(_payload("b", [], 0.3)))       # baseline, low groundedness

    def fake_seam(args, knowledge_arg):
        def run_card_fn(ids):                     # c1 lifts resolved_rate_strict; its placebo does not
            good = "c1" in set(ids) and "placebo-c1" not in set(ids)
            return {"plan_target_recall@1": {"value": 0.5, "n": 5},
                    "resolved_rate_strict": {"value": 0.8 if good else 0.4, "n": 5},
                    "fabrication_rate": {"value": 0.0, "n": 3},
                    "plan_groundedness": {"value": 0.9, "n": 5}, "cost_per_solved": {"value": 1.0, "n": 5},
                    "resolved_by_case": {}}
        return run_card_fn

    monkeypatch.setattr(cli, "_build_attribute_run_card_fn", fake_seam)
    rc = cli.main(["kb-attribute", "--archive", str(d), "--dataset", str(tmp_path), "--index-db", "unused.db",
                   "--repos", str(tmp_path), "--knowledge-store", str(store), "--screen-threshold", "0.1"])
    assert rc == 0
    assert load_knowledge(str(store))["c1"].tier == "applied"    # screened in, confirmed, promoted one rung

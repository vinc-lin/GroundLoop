"""Offline harvester (B3): cluster-by-signature + the split-firewalled candidate minter.

No network / no model / no atlas — pure dict + TOML round-trip through the real validator.
"""
from __future__ import annotations

from groundloop.kb.harvest import candidate_from_cluster, cluster_by_signature
from groundloop.kb.validate import validate_corpus


def _dump_corpus(skill: dict) -> str:
    """Serialize ONE skill dict to a `[[skill]]` corpus TOML (no tomli_w in the venv)."""
    def b(v: object) -> str:  # TOML basic string
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def arr(xs) -> str:
        return "[" + ", ".join(b(x) for x in xs) + "]"

    lines = [
        "[[skill]]",
        f"id = {b(skill['id'])}",
        f"provenance = {b(skill['provenance'])}",
        f"signals = {arr(skill.get('signals', []))}",
        f"hint_apis = {arr(skill.get('hint_apis', []))}",
        "guidance = '''\n" + skill["guidance"] + "\n'''",
        "",
        "[skill.match]",
    ]
    for key, val in skill["match"].items():
        lines.append(f"{key} = {arr(val)}")
    return "\n".join(lines) + "\n"


def _cases() -> list[dict]:
    return [
        {"case_id": "c1", "signals": {"errors": ["NullPointerException"], "libraries": []}},
        {"case_id": "c2", "signals": {"errors": ["NullPointerException"], "packages": ["com.example"]}},
        {"case_id": "c3", "signals": {"errors": [], "libraries": ["libwidget.so"]}},
    ]


def test_cluster_by_signature_groups_by_top_signal():
    groups = cluster_by_signature(_cases())
    assert groups == {"nullpointerexception": ["c1", "c2"], "libwidget.so": ["c3"]}


def test_candidate_eval_and_holdout_splits_are_none():
    # The split firewall: eval/holdout cases may never author a scored playbook.
    assert candidate_from_cluster("NullPointerException", ["c1", "c2"], split_tag="eval") is None
    assert candidate_from_cluster("NullPointerException", ["c1", "c2"], split_tag="holdout") is None


def test_candidate_calib_split_is_validate_clean(tmp_path):
    skill = candidate_from_cluster("NullPointerException", ["c1", "c2"], split_tag="calib")
    assert skill is not None
    assert skill["id"] == "harvest-nullpointerexception"
    for clause in ("Signature:", "Localize:", "Fix:"):
        assert clause in skill["guidance"]
    corpus = tmp_path / "candidate.toml"
    corpus.write_text(_dump_corpus(skill), encoding="utf-8")
    assert validate_corpus(str(corpus)) == []


def test_candidate_train_split_also_mints():
    assert candidate_from_cluster("IllegalStateException", ["c9"], split_tag="train") is not None


def test_candidate_leaky_signature_refused():
    # A signature that is itself a fleet-owner token can't seed a repo-agnostic playbook.
    assert candidate_from_cluster("liboboe.so", ["c1"], split_tag="calib") is None

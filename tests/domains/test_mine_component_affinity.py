import json
from pathlib import Path

from groundloop.domains.android_ivi.mine_component_affinity import build_affinity


def _case(root, cid, component, owner, answerable=True):
    d = Path(root) / cid
    (d / "_oracle").mkdir(parents=True)
    (d / "ticket.json").write_text(json.dumps({"id": cid, "summary": "s", "description": "d",
                                               "component": component}))
    (d / "_oracle" / "oracle.json").write_text(json.dumps(
        {"owning_repo": owner, "is_answerable": answerable}))


def test_build_affinity_counts_cooccurrence(tmp_path):
    _case(tmp_path, "a", "CarPlay", "Core")
    _case(tmp_path, "b", "CarPlay", "Core")
    _case(tmp_path, "c", "CarPlay", "Integ")
    _case(tmp_path, "d", "Audio", "AudioSvc")
    counts = build_affinity(str(tmp_path))
    assert counts["CarPlay"] == {"Core": 2, "Integ": 1}
    assert counts["Audio"] == {"AudioSvc": 1}


def test_build_affinity_skips_empty_component_and_negatives(tmp_path):
    _case(tmp_path, "e", "", "Core")                       # no component
    _case(tmp_path, "f", "WLAN", "__NOT_A_DEFECT__")       # negative owner
    _case(tmp_path, "g", "WLAN", "Net", answerable=False)  # unanswerable
    assert build_affinity(str(tmp_path)) == {}


def test_cli_mine_affinity(tmp_path, capsys):
    import groundloop.cli as cli
    _case(tmp_path, "a", "CarPlay", "Core")
    out = tmp_path / "aff.json"
    assert cli.main(["mine-affinity", "--dataset", str(tmp_path), "--out", str(out)]) == 0
    assert out.exists() and "1 (component,owner)" in capsys.readouterr().out

import json
from pathlib import Path

from groundloop.eval.dataset import CaseRef, case_catalog, load_eval_oracle

NEG = Path(__file__).parent.parent / "fixtures" / "android_ivi" / "negatives"
CATALOG_NAMES = {"android-gpuimage-plus", "organicmaps", "androidx-media", "cameraview"}


def _ref(name: str) -> CaseRef:
    d = NEG / name
    return CaseRef(case_id=d.name, case_dir=str(d))


def test_oof_holdout_fixture_excludes_owner_from_catalog():
    case = _ref("oof-hold-1")
    ev = load_eval_oracle(case)
    assert ev.is_answerable is False and ev.negative_class == "out_of_fleet"
    cat = [r.name for r in case_catalog(case)]
    assert ev.owning_repo not in cat and len(cat) >= 2       # owner held out of THIS ticket's candidates


def test_lowsig_fixture_is_answerable_with_global_catalog():
    case = _ref("lowsig-1")
    ev = load_eval_oracle(case)
    assert ev.is_answerable is True and ev.negative_class == "insufficient_signal"
    assert case_catalog(case) is None                        # falls back to the global catalog


def _norm(s: str) -> str:
    """Lowercase + strip separators so 'Camera View'/'CameraView'/'camera-view' all match 'cameraview'."""
    return s.lower().replace(" ", "").replace("-", "").replace("_", "")


def test_negative_fixtures_are_oracle_blind():
    needles = {_norm(c) for c in CATALOG_NAMES}
    for name in ("oof-hold-1", "lowsig-1"):
        d = NEG / name
        assert not any(n in _norm(name) for n in needles), f"case dir {name} embeds an owner name"
        tj = (d / "ticket.json").read_text()
        raw = json.loads(tj)
        for field in ("id", "summary", "description", "component"):
            hay = _norm(str(raw.get(field, "")))
            assert not any(n in hay for n in needles), f"owner leaked into loop-visible ticket.{field}"
        for hidden in ("is_answerable", "negative_class", "held_out_repo", "owning_repo"):
            assert hidden not in tj, f"{hidden} leaked into loop-visible ticket.json"

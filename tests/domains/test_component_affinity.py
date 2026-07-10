from groundloop.domains.android_ivi.component_affinity import ComponentAffinity


def _aff():
    return ComponentAffinity({"CarPlay": {"Core": 3, "Integ": 1}, "Audio": {"AudioSvc": 1}})


def test_affinity_normalizes():
    a = _aff().affinity("CarPlay")
    assert abs(a["Core"] - 0.75) < 1e-9 and abs(a["Integ"] - 0.25) < 1e-9


def test_affinity_leave_one_out_subtracts_one():
    a = _aff().affinity("CarPlay", exclude="Core")   # Core 3->2, Integ 1 -> total 3
    assert abs(a["Core"] - 2 / 3) < 1e-9 and abs(a["Integ"] - 1 / 3) < 1e-9


def test_affinity_loo_removes_sole_contributor():
    assert _aff().affinity("Audio", exclude="AudioSvc") == {}   # only contributor removed -> empty


def test_affinity_unknown_component_is_empty():
    assert _aff().affinity("Nope") == {}

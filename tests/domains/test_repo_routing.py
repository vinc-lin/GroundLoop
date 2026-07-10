import inspect
from groundloop.domains.android_ivi import repo_routing
from groundloop.domains.android_ivi.repo_routing import route_signals, ROUTES, SONAMES
from groundloop.core.types import Signals


def test_prefix_routes_to_owner():
    sig = Signals(packages=("org.schabi.newpipe.streams",), classes=("SrtWriter",))
    assert ("newpipe", ) == tuple(r for r, _ in route_signals(sig))


def test_soname_routes_to_owner():
    sig = Signals(libraries=("liboboe.so",))
    assert "oboe" in {r for r, _ in route_signals(sig)}


def test_no_match_is_empty():
    assert route_signals(Signals(packages=("com.unknown.pkg",))) == []


def test_antileak_module_reads_no_oracle():
    src = inspect.getsource(repo_routing)
    for banned in ("_oracle", "oracle.json", "load_eval_oracle", "owning_repo", "fault_frame"):
        assert banned not in src, f"routing table must not reference {banned}"


def test_route_is_case_independent():
    sig = Signals(packages=("net.osmand.plus",))
    a = route_signals(sig)
    b = route_signals(sig)   # pure function of Signals; identical regardless of any dataset/case
    assert a == b and a and a[0][0] == "osmand"


def test_route_types():
    assert isinstance(ROUTES, dict) and isinstance(SONAMES, dict)

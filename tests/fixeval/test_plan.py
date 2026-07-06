# tests/fixeval/test_plan.py
from groundloop.fixeval.plan import RepairPlan, PlanTarget, parse_plan, plan_to_dict


def test_parse_fenced_json():
    text = ('```json\n{"root_cause":"npe after onDestroyView","targets":[{"file":"a/F.java",'
            '"symbol":"onBind","why":"null deref"}],"required_apis":["isAdded"],'
            '"strategy":"guard","citations":["a/F.java"],"confidence":0.7}\n```')
    p = parse_plan(text)
    assert isinstance(p, RepairPlan)
    assert p.targets == (PlanTarget(file="a/F.java", why="null deref", symbol="onBind"),)
    assert p.required_apis == ("isAdded",)
    assert p.abstain is False


def test_parse_bare_json_and_string_targets():
    p = parse_plan('prose... {"root_cause":"x","targets":["src/A.java"],"strategy":"y"} trailing')
    assert p.targets == (PlanTarget(file="src/A.java"),)


def test_parse_abstain_and_junk():
    assert parse_plan('{"abstain":true,"root_cause":"","targets":[],"strategy":""}').abstain is True
    assert parse_plan("not json at all") is None
    assert parse_plan("") is None


def test_round_trip_dict():
    p = parse_plan('{"root_cause":"x","targets":[{"file":"A"}],"strategy":"s","required_apis":["k"]}')
    d = plan_to_dict(p)
    assert d["targets"] == [{"file": "A", "symbol": None, "why": ""}]
    assert d["required_apis"] == ["k"]


def test_parse_malformed_confidence_never_raises():
    for bad in ('{"confidence":"high","root_cause":"x","targets":[{"file":"A"}],"strategy":"s"}',
                '{"confidence":[1],"root_cause":"x","targets":[{"file":"A"}],"strategy":"s"}',
                '{"confidence":{},"root_cause":"x","targets":[{"file":"A"}],"strategy":"s"}'):
        p = parse_plan(bad)              # must NOT raise (would abort the whole fixeval batch)
        assert isinstance(p, RepairPlan)
        assert p.confidence == 0.0


def test_parse_non_list_fields_not_char_iterated():
    p = parse_plan('{"root_cause":"x","targets":"src/A.java","required_apis":"k",'
                   '"citations":"c","strategy":"s"}')
    assert isinstance(p, RepairPlan)
    assert p.targets == () and p.required_apis == () and p.citations == ()

from groundloop.fixeval.compare import compare


def test_newly_solved_and_broken():
    base = {"c1": True, "c2": False, "c3": None}
    head = {"c1": False, "c2": True, "c3": True}
    d = compare(base, head)
    assert d["newly_solved"] == ["c2"]          # c2 False->True
    assert d["newly_broken"] == ["c1"]          # c1 True->False; c3 None never counts

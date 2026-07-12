def test_plan_primitives_import_from_fix_package():
    from groundloop.fix.plan import (RepairPlan, PlanTarget, parse_plan,  # noqa: F401
                                     check_plan_in_world, plan_groundedness)  # noqa: F401
    from groundloop.fix.patch import extract_unified_diff, touched_files, norm_path  # noqa: F401
    p = parse_plan('{"root_cause":"x","targets":[{"file":"a.py","symbol":"f","why":"y"}],'
                   '"required_apis":[],"strategy":"s","citations":["a.py"],"risks":[],'
                   '"confidence":0.9,"abstain":false}')
    assert p is not None and p.targets[0].file == "a.py"


def test_planning_engine_does_not_import_fixeval():
    import inspect
    import groundloop.adapters.fix.planning as m
    assert "groundloop.fixeval" not in inspect.getsource(m)


def test_fixeval_shim_still_exports():
    from groundloop.fixeval.plan import RepairPlan, check_plan_in_world, plan_to_dict  # noqa
    from groundloop.fixeval.patch import norm_path, patch_applies  # noqa

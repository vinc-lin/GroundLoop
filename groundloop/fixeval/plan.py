"""Back-compat shim — the plan primitives moved to groundloop.fix.plan (Core-neutral). Kept so the
Dev-Labs fixeval stack + its tests import unchanged. See docs/superpowers/plans/2026-07-13-production-core-defaults-and-loop-closure.md."""
from groundloop.fix.plan import *  # noqa: F401,F403
from groundloop.fix.plan import (PlanTarget, RepairPlan, PlanCheck, parse_plan, plan_to_dict,  # noqa: F401
                                 check_plan_in_world, plan_groundedness)

import inspect

from groundloop.adapters.index.labs import component_prior
from groundloop.domains.android_ivi import component_affinity, component_signals


def test_component_runtime_modules_read_no_oracle():
    for mod in (component_prior, component_affinity, component_signals):
        src = inspect.getsource(mod)
        for banned in ("_oracle", "oracle.json", "load_eval_oracle", "owning_repo", "expected_files"):
            assert banned not in src, f"{mod.__name__} must not reference {banned}"

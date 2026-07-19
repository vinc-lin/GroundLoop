import inspect

from groundloop.adapters.index.labs import functional_text, text_profile
from groundloop.domains.android_ivi import functional_signals


def test_functional_modules_read_no_oracle():
    for mod in (functional_text, text_profile, functional_signals):
        src = inspect.getsource(mod)
        for banned in ("_oracle", "oracle.json", "load_eval_oracle", "owning_repo", "expected_files"):
            assert banned not in src, f"{mod.__name__} must not reference {banned}"

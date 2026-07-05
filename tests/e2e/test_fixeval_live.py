import os

import pytest

_GATE = bool(os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_PRODUCE_API_KEY not set — live GatewayModel skipped")
def test_gateway_model_proposes_a_diff():
    from groundloop.adapters.model.gateway import GatewayModel
    m = GatewayModel(os.environ["KLOOP_PRODUCE_BASE_URL"], os.environ["KLOOP_PRODUCE_API_KEY"],
                     os.environ.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"))
    text = m.complete("Reply with a unified diff (```diff fenced) that adds a line `int x=1;` to file a.c.")
    assert isinstance(text, str)
    assert m.calls == 1 and m.cost_usd >= 0.0

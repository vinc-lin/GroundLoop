"""Hermetic coverage of GatewayModel (cost tracking + graceful fallback) — httpx monkeypatched, no network."""
from groundloop.adapters.model.gateway import GatewayModel


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "```diff\n--- a/x\n+++ b/x\n```"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_gateway_model_parses_and_tracks_cost(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    m = GatewayModel("http://x", "k", "deepseek-chat")
    out = m.complete("fix it")
    assert "```diff" in out
    assert m.calls == 1 and m.input_tokens == 10 and m.output_tokens == 5 and m.cost_usd >= 0.0


def test_gateway_model_graceful_on_error(monkeypatch):
    import httpx

    def _boom(*a, **k):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(httpx, "post", _boom)
    m = GatewayModel("http://x", "k", "deepseek-chat")
    assert m.complete("fix") == "" and m.calls == 1

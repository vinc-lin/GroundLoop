"""Live Model-port impl over the LiteLLM gateway chat endpoint (deepseek-chat via KLOOP_PRODUCE_*).
Cloned from GatewayJudge's httpx/cost pattern. Kept OUT of adapters/mock/ (the hermetic substrate);
CannedModel stays the Type-1 substitute. Live -> Type-2/gated (docs §6.1)."""
from __future__ import annotations

from groundloop.adapters.model.cost import cost_of


class GatewayModel:
    """model.complete(prompt) -> str via the gateway (temperature 0). Tracks cumulative .cost_usd,
    .input_tokens, .output_tokens, .calls. Graceful except -> "" (never crashes the fix eval)."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self.cost_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def complete(self, prompt: str) -> str:
        import httpx
        self.calls += 1
        try:
            resp = httpx.post(self._url, headers={"Authorization": f"Bearer {self._key}"},
                              json={"model": self._model, "temperature": 0,
                                    "messages": [{"role": "user", "content": prompt}]},
                              timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            self.input_tokens += pt
            self.output_tokens += ct
            self.cost_usd += cost_of(pt, ct, self._model)
            return text or ""
        except Exception:      # noqa: BLE001 — never sink the fix eval on a gateway hiccup
            return ""

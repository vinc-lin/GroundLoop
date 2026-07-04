from __future__ import annotations


class CannedModel:
    """Deterministic Model stand-in: returns scripted text keyed by a lookup, else the 'default'."""

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {"default": ""}

    def complete(self, prompt: str) -> str:
        for key, val in self.responses.items():
            if key != "default" and key in prompt:
                return val
        return self.responses.get("default", "")

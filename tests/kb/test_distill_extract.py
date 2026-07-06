"""Phase C (GATED) — oracle-blind distiller: verbatim extraction + owner-token leak-scrub."""
from __future__ import annotations

import pytest

from groundloop.kb.distill import distill_guidance
from groundloop.kb.validate import owner_denylist


def _trace(**kw) -> dict:
    """A LOOP-VISIBLE fix-loop trace (no oracle keys)."""
    base = {
        "ticket_summary": "app crashes on boot",
        "signals": {"errors": ["NullPointerException"]},
        "injected_guidance": (
            "Signature: NullPointerException in onCreate\n"
            "Localize: search the Activity lifecycle callbacks\n"
            "Fix: null-guard the injected binder before use"
        ),
        "patch_diff": "--- a/A.java\n+++ b/A.java\n",
        "helped": True,
    }
    base.update(kw)
    return base


def test_distill_extracts_verbatim_span_from_helped_trace():
    helped = _trace()
    ignored = _trace(
        helped=False,
        injected_guidance="Signature: unrelated\nLocalize: nowhere\nFix: do nothing",
    )
    out = distill_guidance([helped, ignored])
    # non-empty: the helped trace contributed
    assert out.strip()
    # every distilled line is a VERBATIM span of the helped trace's injected_guidance
    for line in out.splitlines():
        assert line in helped["injected_guidance"]
    # the not-helped trace contributed nothing (no free synthesis, no other sources)
    assert "unrelated" not in out
    # leak check re-passes: the distilled guidance names no fleet owner token
    hay = out.lower()
    for tok in owner_denylist():
        assert tok not in hay


def test_distill_leak_scrub_drops_owner_token_lines():
    leak_tok = sorted(owner_denylist())[0]
    helped = _trace(
        injected_guidance=(
            f"Signature: crash referencing {leak_tok} owner\n"
            "Localize: check the service binding\n"
            "Fix: retry the connection with backoff"
        ),
    )
    out = distill_guidance([helped])
    # the owner-token line is scrubbed
    assert leak_tok not in out.lower()
    # clean spans survive verbatim
    assert "Fix: retry the connection with backoff" in out


def test_distill_raises_on_expected_files_oracle_key():
    bad = _trace()
    bad["expected_files"] = ["foo/Bar.java"]
    with pytest.raises(ValueError):
        distill_guidance([bad])


def test_distill_raises_on_owning_repo_oracle_key():
    bad = _trace()
    bad["owning_repo"] = "some-repo"
    with pytest.raises(ValueError):
        distill_guidance([bad])

"""Type-2 gated: the KB arm's bge-m3 rerank on the REAL gateway. Proves the LIVE retrieval plumbing; the
lift magnitude is directional-only on this small seed (spec §5). Skipped without KLOOP_EMBED_API_KEY
(same gate as the sibling live tests). RUNBOOK: KLOOP_EMBED_{BASE_URL,API_KEY,MODEL=bge-m3}."""
import os

import pytest

_GATE = bool(os.environ.get("KLOOP_EMBED_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_EMBED_API_KEY not set — live KB rerank skipped")
def test_live_bge_m3_rerank_returns_capped_ordered_skills():
    from groundloop.adapters.skills.mock import MockSkillRegistry
    from groundloop.engines.atlas.embed import GatewayEmbedder
    from groundloop.config.settings import Settings
    from groundloop.core.types import Signals
    from groundloop.skills.ctx import SkillCtx

    st = Settings.load()
    reg = MockSkillRegistry.load(
        embedder=GatewayEmbedder(st.embed_base_url, st.embed_api_key, st.embed_model), top_k=1)
    ctx = SkillCtx(signals=Signals(), repo="android-gpuimage-plus",
                   text="unsatisfiedlinkerror: couldn't find \"libffmpeg.so\" nativecreatehandler")
    out = reg.select(ctx)
    assert 0 < len(out) <= 1
    assert out[0].id in {"aaos-native-lib-load-failure", "jni-native-handle-lifecycle"}

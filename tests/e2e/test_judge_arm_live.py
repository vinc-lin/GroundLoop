import os
import pytest

_GATE = bool(os.environ.get("KLOOP_PRODUCE_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_PRODUCE_API_KEY not set — live judge arm skipped")
def test_gateway_judge_reranks_live(tmp_path):
    """Live: GatewayJudge reorders candidate repos via the gateway model + tracks cost."""
    from groundloop.adapters.index.atlas_judge import GatewayJudge
    judge = GatewayJudge(os.environ["KLOOP_PRODUCE_BASE_URL"], os.environ["KLOOP_PRODUCE_API_KEY"],
                         os.environ.get("KLOOP_PRODUCE_MAIN_MODEL", "deepseek-chat"))
    order = judge.rerank("UnsatisfiedLinkError native audio underrun liboboe",
                         ["osmand", "oboe", "newpipe"])
    assert set(order) == {"osmand", "oboe", "newpipe"}   # a permutation of the candidates
    assert judge.calls == 1

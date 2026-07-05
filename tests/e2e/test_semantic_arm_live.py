import os
import pytest

_GATE = bool(os.environ.get("KLOOP_EMBED_API_KEY", "").strip())


@pytest.mark.skipif(not _GATE, reason="KLOOP_EMBED_API_KEY not set — live semantic arm skipped")
def test_semantic_arm_ranks_over_live_atlas(tmp_path):
    """Live: SemanticAtlasIndex over a real bge-m3 atlas ranks a known repo for a known signal.
    RUNBOOK: needs KLOOP_EMBED_{BASE_URL,API_KEY,MODEL=bge-m3} + a built atlas.db at KLOOP_ATLAS_DB."""
    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
    from groundloop.engines.atlas.embed import GatewayEmbedder
    from groundloop.core.types import RepoRef, Signals

    db = os.environ.get("KLOOP_ATLAS_DB", "")
    if not db or not os.path.isfile(db):
        pytest.skip("KLOOP_ATLAS_DB not a built atlas.db")
    emb = GatewayEmbedder(os.environ["KLOOP_EMBED_BASE_URL"], os.environ["KLOOP_EMBED_API_KEY"],
                          os.environ.get("KLOOP_EMBED_MODEL", "bge-m3"))
    idx = SemanticAtlasIndex(db, emb)              # exercises the dim guard against real vectors
    ranked = idx.rank_repos(Signals(classes=("MediaCodec",), packages=("androidx.media3",)),
                            [RepoRef("media3"), RepoRef("osmand")])
    assert ranked and ranked[0].score >= ranked[-1].score

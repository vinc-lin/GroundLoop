"""`_build_embedder` (the shared builder for the semantic/functional match arms AND the `--localize
rerank` vector candidate-gen) must thread the configured input caps from Settings, not the library
defaults. Without `max_chars` an oversized input hits the gateway's 413 (payload too large), which the
reranker then swallows into keyword-only — the exact silent degrade sub-tasks 3-4 close. Assert the
built embedder carries `max_chars`/`batch` from `KLOOP_EMBED_MAX_CHARS`/`KLOOP_EMBED_BATCH`."""
from __future__ import annotations


def test_build_embedder_threads_embed_caps(monkeypatch):
    monkeypatch.setenv("KLOOP_EMBED_BASE_URL", "http://stub-gateway")
    monkeypatch.setenv("KLOOP_EMBED_MAX_CHARS", "1234")
    monkeypatch.setenv("KLOOP_EMBED_BATCH", "17")
    from groundloop.cli import _build_embedder
    from groundloop.config.settings import Settings
    emb = _build_embedder()
    st = Settings.load()
    assert emb is not None
    assert emb.max_chars == st.embed_max_chars == 1234   # configured cap, NOT the library default (8000)
    assert emb.batch == st.embed_batch == 17


def test_build_embedder_none_without_base_url(monkeypatch):
    monkeypatch.delenv("KLOOP_EMBED_BASE_URL", raising=False)
    from groundloop.cli import _build_embedder
    assert _build_embedder() is None

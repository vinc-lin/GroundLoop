"""GatewayEmbedder input-cap behavior — truncation + batching (no network; _post_batch stubbed).

These guard the fix for the bge-m3 server's input caps (BGE_MAX_BATCH / BGE_MAX_CHARS → HTTP 413,
which is a non-retried 4xx that would abort a whole index). See ~/bge-m3/README.md."""
from groundloop.engines.atlas.embed import GatewayEmbedder


def _capturing_embedder(**kw):
    """A GatewayEmbedder whose network call is replaced by a recorder of the chunks it receives."""
    emb = GatewayEmbedder("http://x/v1", "k", "bge-m3", **kw)
    seen: list[list[str]] = []

    def fake_post(chunk):
        seen.append(list(chunk))
        return [[0.0] for _ in chunk]

    emb._post_batch = fake_post  # type: ignore[method-assign]
    return emb, seen


def test_truncates_each_input_to_max_chars():
    emb, seen = _capturing_embedder(batch=4, max_chars=10)
    out = emb.embed(["short", "x" * 5000])
    assert len(out) == 2                      # one vector per input, order preserved
    sent = [t for chunk in seen for t in chunk]
    assert sent[0] == "short"                 # short input untouched
    assert len(sent[1]) == 10                 # long input clipped to max_chars (no 413)


def test_batches_at_batch_size():
    emb, seen = _capturing_embedder(batch=2, max_chars=1000)
    emb.embed([f"t{i}" for i in range(5)])
    assert [len(c) for c in seen] == [2, 2, 1]   # 5 inputs @ batch 2 → 2 + 2 + 1


def test_defaults_respect_server_caps():
    # Defaults must stay within the server's BGE_MAX_BATCH=256 and well under BGE_MAX_CHARS=100000.
    emb = GatewayEmbedder("http://x/v1", "k", "bge-m3")
    assert emb.batch <= 256
    assert emb.max_chars <= 100000

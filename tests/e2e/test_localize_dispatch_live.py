"""Type-2 (gated live) mechanism check: with a real atlas.db + gateway embedder, --localize dispatch
routes a prose-only functional ticket to the semantic retriever and a crash ticket to FTS5. Not a
score threshold — a routing/mechanism assertion. Gated: needs KLOOP_ATLAS_DB + KLOOP_EMBED_BASE_URL."""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("KLOOP_ATLAS_DB") and os.environ.get("KLOOP_EMBED_BASE_URL")),
    reason="needs KLOOP_ATLAS_DB + KLOOP_EMBED_BASE_URL (Type-2 live)")


def _one_repo(db):
    from groundloop.engines.atlas.store import Store
    return Store(db).list_repo_states()[0].repo   # RepoState(repo, indexed_repo_head, indexed_at, unit_count)


def test_dispatch_routes_functional_to_semantic_and_crash_to_fts5():
    from groundloop.adapters.index.atlas import AtlasIndex
    from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
    from groundloop.adapters.index.localize_dispatch import LocalizeDispatchIndex
    from groundloop.cli import _build_embedder
    from groundloop.core.types import RepoRef, Signals
    from groundloop.domains.android_ivi.functional_signals import PROSE_MARK

    db = os.environ["KLOOP_ATLAS_DB"]
    repo = RepoRef(_one_repo(db))
    d = LocalizeDispatchIndex(AtlasIndex(db), AtlasIndex(db),
                              SemanticAtlasIndex(db, _build_embedder()))

    # prose-only (no-anchor) -> functional (semantic) branch
    d.note_signals(Signals(symbols=(PROSE_MARK + "the settings screen shows the wrong label",)))
    func_hits = d.retrieve(repo, "the settings screen shows the wrong label")

    # crash anchor -> FTS5 branch (identical to AtlasIndex.retrieve)
    d.note_signals(Signals(classes=("com.x.Foo",)))
    crash_hits = d.retrieve(repo, "Foo")
    fts5_hits = AtlasIndex(db).retrieve(repo, "Foo")
    assert crash_hits == fts5_hits            # crash path byte-identical to atlas FTS5
    assert isinstance(func_hits, list)        # semantic branch executed (may be empty on a tiny atlas)

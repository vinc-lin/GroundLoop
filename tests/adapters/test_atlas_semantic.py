import pytest

from groundloop.engines.atlas.store import Store, Unit
from groundloop.adapters.index.atlas_semantic import SemanticAtlasIndex
from groundloop.core.types import RepoRef, Signals


class _FakeEmbedder:
    """Returns a fixed query vector regardless of text (controllable for tests)."""
    def __init__(self, vec):
        self._vec = vec

    def embed(self, texts):
        return [list(self._vec) for _ in texts]


def _build_vec_atlas(path):
    """3 repos, one symbol unit each, orthogonal 3-dim vectors."""
    s = Store(path)
    specs = {"repo_a": [1.0, 0.0, 0.0], "repo_b": [0.0, 1.0, 0.0], "repo_c": [0.0, 0.0, 1.0]}
    for repo, vec in specs.items():
        u = Unit(repo=repo, kind="symbol", name="Sym", qualified_name=f"{repo}.Sym",
                 file=f"{repo}/src.ext", repo_head="fix", text="Sym", meta={})
        s.reindex_repo(repo, [(u, vec)], repo_head="fix")
    return path


def test_rank_repos_by_cosine_favours_matching_repo(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))
    # query vector aligned with repo_b -> repo_b should rank first
    idx = SemanticAtlasIndex(db, _FakeEmbedder([0.1, 0.9, 0.0]))
    sig = Signals(classes=("Whatever",))
    ranked = idx.rank_repos(sig, [RepoRef("repo_a"), RepoRef("repo_b"), RepoRef("repo_c")])
    assert ranked[0].repo.name == "repo_b"
    assert ranked[0].score > ranked[1].score


def test_rank_repos_restricts_to_catalog(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))
    idx = SemanticAtlasIndex(db, _FakeEmbedder([1.0, 0.0, 0.0]))
    ranked = idx.rank_repos(Signals(classes=("X",)), [RepoRef("repo_a"), RepoRef("repo_c")])
    assert {r.repo.name for r in ranked} == {"repo_a", "repo_c"}   # repo_b excluded
    assert ranked[0].repo.name == "repo_a"


def test_reuse_contract_guard_rejects_dim_mismatch(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))          # indexed vectors are 3-dim
    with pytest.raises(ValueError, match="(?i)dim"):
        SemanticAtlasIndex(db, _FakeEmbedder([1.0, 0.0]))       # 2-dim query -> mismatch


def test_retrieve_returns_files_for_repo(tmp_path):
    db = _build_vec_atlas(str(tmp_path / "atlas.db"))
    idx = SemanticAtlasIndex(db, _FakeEmbedder([1.0, 0.0, 0.0]))
    files = idx.retrieve(RepoRef("repo_a"), "anything")
    assert files == ["repo_a/src.ext"]

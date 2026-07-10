from groundloop.adapters.index.text_profile import build_text_profiles, gather_repo_texts
from groundloop.engines.atlas.embed import StubEmbedder
from groundloop.engines.atlas.store import Store


def test_build_text_profiles_writes_repo_vectors(tmp_path):
    db = str(tmp_path / "profiles.db")
    build_text_profiles({"oboe": ["audio playback streaming", "low latency"],
                         "newpipe": ["video player youtube"]}, db, StubEmbedder(dim=16))
    store = Store(db)
    qvec = StubEmbedder(dim=16).embed(["audio playback"])[0]
    hits = store.vector_search(qvec, k=5, repos=["oboe", "newpipe"])
    assert hits and hits[0][0].repo == "oboe"          # audio query nearest to oboe profile


def test_gather_repo_texts_reads_readme(tmp_path):
    repo = tmp_path / "myrepo"
    (repo / "app").mkdir(parents=True)
    (repo / "README.md").write_text("# MyRepo\nHandles audio playback and Bluetooth routing.")
    (repo / "app" / "build.gradle").write_text('android { namespace "com.acme.audio" }')
    chunks = gather_repo_texts(str(repo))
    joined = " ".join(chunks).lower()
    assert "audio playback" in joined and "com.acme.audio" in joined

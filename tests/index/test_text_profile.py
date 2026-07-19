from groundloop.adapters.index.labs.text_profile import build_text_profiles, gather_repo_texts
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
    assert any("app" in c for c in chunks)                 # real subdir identifier still collected


def test_gather_repo_texts_prunes_vendor_dirs(tmp_path):
    repo = tmp_path / "myrepo"
    (repo / "node_modules" / "foo").mkdir(parents=True)
    (repo / ".git").mkdir(parents=True)
    (repo / "README.md").write_text("real audio playback text")
    (repo / "node_modules" / "foo" / "README.md").write_text("VENDORLEAK bundled dependency prose")
    (repo / ".git" / "config").write_text("GITLEAK internal git config")
    joined = " ".join(gather_repo_texts(str(repo)))
    assert "VENDORLEAK" not in joined and "GITLEAK" not in joined and "node_modules" not in joined
    assert "audio playback" in joined


def test_gather_repo_texts_bounded_and_prioritized(tmp_path):
    repo = tmp_path / "bigrepo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("# BigRepo\nDISTINCTIVEWORD lives here in the readme.")
    for i in range(20):
        deep = repo / "modules" / f"mod{i}" / "src" / "main" / "java" / "com" / "acme" / f"pkg{i}"
        deep.mkdir(parents=True)
    chunks = gather_repo_texts(str(repo), max_chunks=5)
    assert len(chunks) <= 5
    assert any("DISTINCTIVEWORD" in c for c in chunks)          # README must survive a tiny cap

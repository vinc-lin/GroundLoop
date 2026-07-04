from groundloop.config.settings import Settings


def test_defaults_and_env_override(monkeypatch, tmp_path):
    s = Settings.load(env={})
    assert s.domain == "android_ivi" and s.data_dir.endswith("data")
    s2 = Settings.load(env={"KLOOP_DATA_DIR": str(tmp_path), "KLOOP_DOMAIN": "x"})
    assert s2.data_dir == str(tmp_path) and s2.domain == "x"


def test_index_settings_defaults_and_env(monkeypatch, tmp_path):
    from groundloop.config.settings import Settings
    s = Settings.load(env={"KLOOP_ATLAS_DB": str(tmp_path / "a.db")})
    assert s.atlas_db.endswith("a.db")
    assert s.embed_model == "bge-m3"          # PINNED default
    s2 = Settings.load(env={"KLOOP_EMBED_MODEL": "other"})
    assert s2.embed_model == "other"

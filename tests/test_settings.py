from groundloop.config.settings import Settings


def test_defaults_and_env_override(monkeypatch, tmp_path):
    s = Settings.load(env={})
    assert s.domain == "android_ivi" and s.data_dir.endswith("data")
    s2 = Settings.load(env={"KLOOP_DATA_DIR": str(tmp_path), "KLOOP_DOMAIN": "x"})
    assert s2.data_dir == str(tmp_path) and s2.domain == "x"

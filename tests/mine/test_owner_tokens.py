from groundloop.domains.android_ivi.owner_tokens import FLEET_OWNER_TOKENS, owner_tokens_for


def test_all_nine_repos_present():
    assert set(FLEET_OWNER_TOKENS) == {
        "osmand", "organicmaps", "antennapod", "newpipe", "oboe",
        "cameraview", "dlt-daemon", "media3", "android-gpuimage-plus",
    }


def test_media3_gotcha_namespace_is_owner_side():
    # androidx.media3 is owner-identifying for media3 (not a generic keep)
    assert "androidx.media3" in FLEET_OWNER_TOKENS["media3"]["namespaces"]
    # ...but antennapod/newpipe KEEP androidx.media3.* as a dependency signal
    assert any("androidx.media3" in k for k in FLEET_OWNER_TOKENS["antennapod"]["KEEP"])


def test_owner_tokens_for_returns_row_with_required_keys():
    row = owner_tokens_for("oboe")
    assert row["namespaces"] == ["oboe::"]
    assert "liboboe.so" in row["sonames"]
    for key in ("namespaces", "slugs", "sonames", "KEEP"):
        assert key in row


def test_unknown_repo_raises():
    import pytest
    with pytest.raises(KeyError):
        owner_tokens_for("not-a-repo")

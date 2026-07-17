from groundloop.engines.atlas.tokenize import split_identifier


def test_splits_pascal_case():
    assert split_identifier("ScreenshotUtils") == ["screenshot", "utils"]


def test_splits_camel_and_snake_and_digits():
    assert split_identifier("logManagementFragment") == ["log", "management", "fragment"]
    assert split_identifier("HTTP2Client") == ["http", "2", "client"]
    assert split_identifier("audio_focus_helper") == ["audio", "focus", "helper"]


def test_single_word_returns_itself_lowercased():
    assert split_identifier("Screenshot") == ["screenshot"]


def test_empty_and_symbols():
    assert split_identifier("") == []
    assert split_identifier("__") == []

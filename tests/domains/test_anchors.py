from groundloop.domains.android_ivi.anchors import extract_anchor_candidates


def test_extracts_quoted_and_extension_and_camelcase():
    text = 'System screenshots have the extension JPG instead of PNG in ScreenshotUtils'
    got = extract_anchor_candidates(text)
    assert "JPG" in got and "PNG" in got            # ALL-CAPS extension tokens
    assert "ScreenshotUtils" in got                 # CamelCase identifier in prose
    assert "screenshots" not in got                 # a plain lowercase english word is not an anchor


def test_quoted_spans_and_backticks():
    got = extract_anchor_candidates('the label reads "Border Crossing" not `BorderCrossingService`')
    assert "Border Crossing" in got                 # quoted phrase kept as a phrase
    assert "BorderCrossingService" in got           # backtick code span


def test_stoplist_and_dedup():
    got = extract_anchor_candidates("the App fails when the ERROR is shown and the App logs ERROR")
    assert "App" not in got and "the" not in got    # common words stoplisted
    assert got.count("ERROR") <= 1                   # deduped

from groundloop.domains.android_ivi.anchors import (
    extract_anchor_candidates,
    rare_anchors,
)


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


class _StubStore:
    def __init__(self, hits_by_q):
        self._h = hits_by_q
    def keyword_search(self, q, k=20, repos=None, kinds=None):
        n = self._h.get(q, 0)
        return [(type("U", (), {"file": f"f{i}.kt"})(), i) for i in range(min(n, k))]


def test_rarity_gate_drops_overmatching_keeps_rare():
    store = _StubStore({"PNG": 3, "log": 500, "ScreenshotUtils": 1, "missing": 0})
    got = rare_anchors(["log", "PNG", "ScreenshotUtils", "missing"], store, "r",
                       max_files=40, max_anchors=6)
    assert "PNG" in got and "ScreenshotUtils" in got   # rare -> kept
    assert "log" not in got                             # over-matches (>40) -> dropped
    assert "missing" not in got                         # zero hits -> dropped (nothing to anchor)
    assert got == sorted(got, key=lambda a: {"ScreenshotUtils": 1, "PNG": 3}[a])  # rarest first

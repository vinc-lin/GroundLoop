"""load_corpus parses corpus.toml -> {name: (url, sha)}, normalizing placeholder SHAs."""
from __future__ import annotations

from groundloop.build.corpus import load_corpus


def _write(tmp_path, body):
    p = tmp_path / "corpus.toml"
    p.write_text(body)
    return str(p)


def test_parses_url_and_sha(tmp_path):
    path = _write(tmp_path, '''
[[repo]]
name = "alpha"
url = "https://example.test/alpha.git"
sha = "abc1234def5678"

[[repo]]
name = "beta"
url = "https://example.test/beta.git"
sha = "PIN_AT_CLONE"

[[repo]]
name = "gamma"
url = "https://example.test/gamma.git"
''')
    corpus = load_corpus(path)
    assert corpus["alpha"] == ("https://example.test/alpha.git", "abc1234def5678")
    # placeholder + missing sha both normalize to "" (clone HEAD, pin later)
    assert corpus["beta"] == ("https://example.test/beta.git", "")
    assert corpus["gamma"] == ("https://example.test/gamma.git", "")


def test_skips_entries_without_url(tmp_path):
    path = _write(tmp_path, '''
[[repo]]
name = "hasurl"
url = "https://example.test/x.git"

[[repo]]
name = "nourl"
sha = "deadbeef"
''')
    corpus = load_corpus(path)
    assert "hasurl" in corpus
    assert "nourl" not in corpus

"""Composition root: `--fix-context {codewiki,cbm}` builds a FixContextProvider; unset -> None (opt-in,
default byte-identical). Fail-safe: codewiki without a registry still builds (entity_map None -> empty
CodeWiki); cbm builds a lazy per-repo callable that does NOT spin up a CBM subprocess at construction."""
from types import SimpleNamespace

from groundloop.cli import _build_fix_context
from tests.fixtures.fix_atlas_fixture import build_fix_atlas_fixture


def test_default_unset_returns_none(tmp_path):
    assert _build_fix_context(SimpleNamespace(fix_context="", index_db="x", repos="y")) is None


def test_codewiki_builds_provider_failsafe_without_registry(tmp_path, monkeypatch):
    monkeypatch.delenv("KLOOP_REGISTRY", raising=False)
    db = build_fix_atlas_fixture(str(tmp_path / "atlas.db"))
    prov = _build_fix_context(SimpleNamespace(fix_context="codewiki", index_db=db, repos=str(tmp_path)))
    assert prov is not None
    assert prov.store is not None and prov.entity_map is None and prov.cbm is None


def test_cbm_builds_lazy_provider_without_subprocess(tmp_path):
    prov = _build_fix_context(SimpleNamespace(fix_context="cbm", index_db="unused", repos=str(tmp_path)))
    assert prov is not None
    assert prov.store is None and callable(prov.cbm)     # lazy: open_cbm not called until a repo is queried


def test_unknown_kind_ignored_returns_none(tmp_path, capsys):
    assert _build_fix_context(SimpleNamespace(fix_context="bogus", index_db="x", repos="y")) is None
    assert "unknown context kind" in capsys.readouterr().out

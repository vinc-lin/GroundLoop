"""Task 11: harden the `gloop run --fixer model/plan` --repos guard.

The presence-only guard (`if not args.repos:`) only checked that --repos is a NON-EMPTY string. A
wrong-but-nonempty --repos passes it yet yields EMPTY worktrees (CheckoutEstate makes an empty dir when a
repo snapshot is missing) — re-opening the exact fabrication risk the guard closes. The hardened guard
must verify the --repos dir actually holds a snapshot subdir for at least one catalog repo.

KLOOP_PRODUCE_API_KEY is set so the key check passes and control reaches the --repos check. The catalog
is a JSON list of {"name": ...} objects (matches tests/fixtures/android_ivi/catalog.json).
"""
from __future__ import annotations

import json

from groundloop.cli import _repos_has_snapshots, main


def _write_catalog(tmp_path, names):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps([{"name": n} for n in names]))
    return cat


def _run(tmp_path, repos):
    """Drive `gloop run --fixer plan` to the --repos guard; return (rc, stdout)."""
    return main(["run",
                 "--dataset", str(tmp_path / "ds"),
                 "--catalog", str(tmp_path / "catalog.json"),
                 "--work", str(tmp_path / "work"),
                 "--changes", str(tmp_path / "ch"),
                 "--index-db", str(tmp_path / "atlas.db"),
                 "--out", str(tmp_path / "out"),
                 "--repos", str(repos),
                 "--fixer", "plan"])


# --- guard at the main() level ---------------------------------------------------------------------

def test_missing_repos_dir_rejected(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KLOOP_PRODUCE_API_KEY", "x")
    _write_catalog(tmp_path, ["repo-a", "repo-b"])
    rc = _run(tmp_path, tmp_path / "does-not-exist")
    out = capsys.readouterr().out
    assert rc == 2
    assert "snapshots" in out


def test_empty_repos_dir_rejected(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KLOOP_PRODUCE_API_KEY", "x")
    _write_catalog(tmp_path, ["repo-a", "repo-b"])
    repos = tmp_path / "repos"
    (repos / "unrelated").mkdir(parents=True)      # a subdir, but NOT for any catalog repo
    rc = _run(tmp_path, repos)
    out = capsys.readouterr().out
    assert rc == 2
    assert "snapshots" in out


def test_repos_dir_with_catalog_snapshot_passes_guard(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KLOOP_PRODUCE_API_KEY", "x")
    _write_catalog(tmp_path, ["repo-a", "repo-b"])
    repos = tmp_path / "repos"
    (repos / "repo-a").mkdir(parents=True)         # a snapshot subdir for a catalog repo
    (tmp_path / "ds").mkdir()                       # empty dataset -> run_dataset processes 0 cases
    # Passes the --repos guard; may proceed to a clean 0-case run. Assert the guard did NOT fire.
    rc = _run(tmp_path, repos)
    out = capsys.readouterr().out
    assert "snapshots" not in out                   # the --repos guard message is the only "snapshots"
    assert rc != 2                                  # not the guard's fail-closed rc


# --- the helper directly ---------------------------------------------------------------------------

def test_helper_true_when_catalog_subdir_present(tmp_path):
    cat = _write_catalog(tmp_path, ["repo-a", "repo-b"])
    repos = tmp_path / "repos"
    (repos / "repo-b").mkdir(parents=True)
    assert _repos_has_snapshots(str(repos), str(cat)) is True


def test_helper_false_for_missing_empty_and_blank(tmp_path):
    cat = _write_catalog(tmp_path, ["repo-a"])
    assert _repos_has_snapshots(str(tmp_path / "missing"), str(cat)) is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _repos_has_snapshots(str(empty), str(cat)) is False
    assert _repos_has_snapshots("", str(cat)) is False


def test_helper_false_when_catalog_unreadable(tmp_path):
    repos = tmp_path / "repos"
    (repos / "repo-a").mkdir(parents=True)
    assert _repos_has_snapshots(str(repos), str(tmp_path / "no-such-catalog.json")) is False

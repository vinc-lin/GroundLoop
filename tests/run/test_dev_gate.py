"""Production-surface guard: `gloop run --index` / `--fixer canned` / `--case` are dev-only and must be
rejected (rc=2) unless the dev gate is armed (KLOOP_DEV=1 or the hidden --dev flag).

The suite-wide autouse fixture (tests/conftest.py::_hermetic_dev_mode) arms the gate for every other
test; each test here opts OUT via the SAME function-scoped monkeypatch (delenv undoes the autouse
setenv), so the gate is genuinely OFF for the rejection assertions below.
"""
from __future__ import annotations


def test_index_rejected_without_dev(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_DEV", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index", "tok.json", "--out", "o", "--repos", "r"])
    assert rc == 2 and "dev-only" in capsys.readouterr().out.lower()


def test_canned_rejected_without_dev(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_DEV", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index-db", "a.db", "--out", "o", "--repos", "r", "--fixer", "canned"])
    assert rc == 2 and "dev" in capsys.readouterr().out.lower()


def test_case_rejected_without_dev(monkeypatch, capsys):
    monkeypatch.delenv("KLOOP_DEV", raising=False)
    from groundloop.cli import main
    rc = main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
               "--index-db", "a.db", "--case", "X"])
    assert rc == 2 and "dev" in capsys.readouterr().out.lower()


def test_index_allowed_with_dev_env(monkeypatch, capsys):
    monkeypatch.setenv("KLOOP_DEV", "1")
    from groundloop.cli import main
    # With the gate ON, --index passes the gate. It may fail LATER for unrelated reasons (missing
    # tok.json etc.) — assert only that the dev gate did NOT reject it (no "dev-only" rejection printed).
    try:
        main(["run", "--dataset", "d", "--catalog", "c", "--work", "w", "--changes", "ch",
              "--index", "tok.json", "--out", "o", "--repos", "r", "--fixer", "canned"])
    except Exception:
        pass  # downstream failure past the gate is fine; we only assert the gate let it through
    assert "dev-only" not in capsys.readouterr().out.lower()

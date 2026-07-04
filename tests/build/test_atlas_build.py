"""build_atlas orchestrates clone -> produce -> index -> doctor with injected steps."""
from __future__ import annotations

from groundloop.build.atlas_build import build_atlas, BuildReport


def _fake_toml(tmp_path):
    p = tmp_path / "atlas.toml"
    p.write_text(
        '[[repo]]\nname = "a"\nrepo_path = "%s/a"\nwiki_dir = "%s/_wiki/a"\n'
        % (tmp_path, tmp_path)
    )
    return str(p)


def test_happy_path_runs_all_steps_in_order(tmp_path):
    order = []

    def fake_clone(entries, **kw):
        order.append("clone")
        return {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()}

    def fake_produce(entries, **kw):
        order.append("produce")
        return {"a": type("R", (), {"status": "ok", "name": "a", "detail": ""})()}

    def fake_index(registry):
        order.append(("index", registry))
        return 0

    def fake_doctor():
        order.append("doctor")
        return 0

    report = build_atlas(
        _fake_toml(tmp_path), jobs=2, concurrency=4,
        clone_fn=fake_clone, produce_fn=fake_produce,
        index_fn=fake_index, doctor_fn=fake_doctor,
    )

    assert [o if isinstance(o, str) else o[0] for o in order] == \
        ["clone", "produce", "index", "doctor"]
    assert isinstance(report, BuildReport)
    assert report.ok is True


def test_produce_failure_stops_before_index(tmp_path):
    calls = []

    def fake_clone(entries, **kw):
        return {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()}

    def fake_produce(entries, **kw):
        return {"a": type("R", (), {"status": "failed", "name": "a", "detail": "boom"})()}

    def fake_index(registry):
        calls.append("index")
        return 0

    report = build_atlas(
        _fake_toml(tmp_path),
        clone_fn=fake_clone, produce_fn=fake_produce,
        index_fn=fake_index, doctor_fn=lambda: 0,
    )

    assert calls == []                 # index never ran
    assert report.ok is False
    assert "produce" in report.failed_stage


def test_index_nonzero_marks_build_failed(tmp_path):
    report = build_atlas(
        _fake_toml(tmp_path),
        clone_fn=lambda e, **k: {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()},
        produce_fn=lambda e, **k: {"a": type("R", (), {"status": "ok", "name": "a", "detail": ""})()},
        index_fn=lambda registry: 3,
        doctor_fn=lambda: 0,
    )
    assert report.ok is False
    assert report.failed_stage == "index"


def test_build_atlas_passes_corpus_urls_to_clone(tmp_path):
    seen = {}

    def fake_clone(fleet, **kw):
        for fr in fleet:
            seen[fr.name] = (fr.url, fr.sha)
        return {"a": type("R", (), {"status": "cloned", "sha": "s", "name": "a"})()}

    build_atlas(
        _fake_toml(tmp_path),
        corpus={"a": ("https://example.test/a.git", "sha123")},
        clone_fn=fake_clone,
        produce_fn=lambda e, **k: {"a": type("R", (), {"status": "ok", "name": "a", "detail": ""})()},
        index_fn=lambda registry: 0,
        doctor_fn=lambda: 0,
    )

    assert seen["a"] == ("https://example.test/a.git", "sha123")

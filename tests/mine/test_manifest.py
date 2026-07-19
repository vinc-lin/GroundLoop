from groundloop.mine.manifest import E2ECase, write_manifest, load_manifest

_CASE = E2ECase(repo="oboe", issue_number=1417, issue_url="https://github.com/google/oboe/issues/1417",
                pr_number=1420, pr_url="https://github.com/google/oboe/pull/1420",
                base_sha="a"*40, fix_sha="b"*40, owning_repo="oboe",
                expected_files=("src/flowgraph/FlowGraphNode.cpp",), required_apis=("pullData",))


def test_manifest_roundtrip(tmp_path):
    p = tmp_path / "m.toml"
    write_manifest([_CASE], p)
    assert load_manifest(p) == [_CASE]


def test_manifest_is_recipe_and_oracle_only(tmp_path):
    p = tmp_path / "m.toml"
    write_manifest([_CASE], p)
    text = p.read_text()
    assert "fix_patch" not in text and "diff" not in text and "\nlogs" not in text


def test_manifest_deterministic_sorted(tmp_path):
    c2 = E2ECase(repo="oboe", issue_number=99, issue_url="u", pr_number=1, pr_url="u",
                 base_sha="a"*40, fix_sha="b"*40, owning_repo="oboe", expected_files=(), required_apis=())
    p1 = tmp_path/"a.toml"
    p2 = tmp_path/"b.toml"
    write_manifest([_CASE, c2], p1)
    write_manifest([c2, _CASE], p2)
    assert p1.read_text() == p2.read_text()          # order-independent (sorted)
    assert load_manifest(p1)[0].issue_number == 99   # 99 sorts before 1417

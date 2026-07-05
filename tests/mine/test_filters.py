from groundloop.mine.filters import production_files, is_minable


def _f(name, status="modified", adds=5, dels=2):
    return {"filename": name, "status": status, "additions": adds, "deletions": dels}


def test_production_files_keeps_source_drops_test_doc_build():
    files = [
        _f("app/src/main/java/com/x/Foo.java"),
        _f("app/src/test/java/com/x/FooTest.java"),
        _f("app/src/androidTest/java/com/x/FooIT.java"),
        _f("README.md"),
        _f("docs/guide.md"),
        _f("gradle.properties"),
        _f("src/test/resources/mocks/data.json"),
    ]
    prod = production_files(files)
    assert prod == ["app/src/main/java/com/x/Foo.java"]


def test_minable_requires_production_source_and_small_diff():
    ok = [_f("src/main/java/A.java")]
    assert is_minable({"merged": True, "changed_files": 1}, ok, max_files=5) is True


def test_reject_merge_and_revert_and_unmerged():
    ok = [_f("src/main/java/A.java")]
    assert is_minable({"merged": False, "changed_files": 1}, ok, max_files=5) is False
    assert is_minable({"merged": True, "changed_files": 1, "title": "Merge branch main"}, ok, max_files=5) is False
    assert is_minable({"merged": True, "changed_files": 1, "title": "Revert \"fix X\""}, ok, max_files=5) is False


def test_reject_too_many_files_and_no_production_files():
    ok = [_f(f"src/main/java/A{i}.java") for i in range(6)]
    assert is_minable({"merged": True, "changed_files": 6}, ok, max_files=5) is False   # >max_files
    docs = [_f("README.md"), _f("docs/x.md")]
    assert is_minable({"merged": True, "changed_files": 2}, docs, max_files=5) is False  # no production files

from groundloop.fix.patch import canonical_path
from groundloop.eval.metrics import recall_at_k


def test_canonical_path_reconciles_source_roots():
    atlas = "app/src/main/java/com/ecarx/connectivityservice/vehicle/DefaultNameProcessor.java"
    oracle = "src/java/com/ecarx/connectivityservice/vehicle/DefaultNameProcessor.java"
    assert canonical_path(atlas) == canonical_path(oracle)
    assert canonical_path(atlas) == "com/ecarx/connectivityservice/vehicle/DefaultNameProcessor.java"


def test_canonical_path_distinct_files_do_not_collide():
    a = canonical_path("app/src/main/java/com/x/foo/Util.java")
    b = canonical_path("app/src/main/java/com/x/bar/Util.java")
    assert a != b   # full package path kept -> same basename in different packages stays distinct


def test_canonical_path_kotlin_and_plain_fallback():
    assert canonical_path("m/src/main/kotlin/com/x/A.kt") == "com/x/A.kt"
    assert canonical_path("library/src/main/jni/foo.cpp").endswith("foo.cpp")  # non-jvm: still normalized


def test_recall_matches_after_canonicalization():
    retrieved = ["app/src/main/java/com/ecarx/x/DefaultNameProcessor.java"]
    expected = ["src/java/com/ecarx/x/DefaultNameProcessor.java"]
    r = recall_at_k([canonical_path(x) for x in retrieved], {canonical_path(e) for e in expected}, 1)
    assert r == 1.0

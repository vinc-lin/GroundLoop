import json


def test_write_manifest_records_provenance(tmp_path):
    from groundloop.run.manifest import write_manifest

    out = tmp_path / "out"
    atlas = tmp_path / "atlas.db"
    atlas.write_bytes(b"fake atlas bytes")
    aff = tmp_path / "affinity.json"
    aff.write_text(json.dumps({"Audio": ["alpha"]}))

    p = write_manifest(str(out), atlas_db=str(atlas), match_arm="component", fixer="plan",
                       affinity=str(aff), produce_model="deepseek-chat", embed_model="bge-m3",
                       n_cases=3)
    assert p == str(out / "manifest.json")
    assert (out / "manifest.json").exists()
    m = json.loads((out / "manifest.json").read_text())

    assert isinstance(m["timestamp"], str) and m["timestamp"]          # ISO-8601 string
    assert m["atlas_db"] == str(atlas)
    assert isinstance(m["atlas_identity"], str) and m["atlas_identity"]  # non-empty for a real file
    assert m["match_arm"] == "component"
    assert m["fixer"] == "plan"
    assert isinstance(m["affinity"], dict) and m["affinity"]["sha1"]   # hash present for a real file
    assert m["model_pins"] == {"produce": "deepseek-chat", "embed": "bge-m3"}
    assert m["change_sink"] == "mock"
    assert m["n_cases"] == 3


def test_write_manifest_empty_atlas_and_affinity(tmp_path):
    from groundloop.run.manifest import write_manifest

    out = tmp_path / "out"
    write_manifest(str(out), atlas_db=None, match_arm="flood", fixer="canned",
                   affinity="", produce_model="deepseek-chat", embed_model="bge-m3", n_cases=0)
    m = json.loads((out / "manifest.json").read_text())
    assert m["atlas_identity"] == ""      # atlas_db None -> empty identity
    assert m["atlas_db"] == ""
    assert m["affinity"] == ""            # no affinity artifact -> empty
    assert m["n_cases"] == 0

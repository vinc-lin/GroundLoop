from groundloop.faulteval.metrics import grade_fault_localization, FaultLocRecord


def _rec(cid, top, blamed, fhint, conf="HIGH"):
    return FaultLocRecord(case_id=cid, top_frame_key=top, blamed_keys=blamed,
                          fault_file_hint=fhint, confidence=conf)


def test_frame_and_file_hits():
    recs = [_rec("A", "org.osm.F.run", ["org.osm.F.run", "android.os.Handler.dispatch"], "F.java"),
            _rec("B", "android.os.X.y", ["android.os.X.y", "org.osm.G.go"], "X.java")]
    oracle = {"A": {"fault_frame": "org.osm.F.run", "fault_file": "app/osm/F.java"},
              "B": {"fault_frame": "org.osm.G.go", "fault_file": "app/osm/G.java"}}
    card = grade_fault_localization(recs, oracle_by_case=oracle, k=5)
    assert card["frame@1"]["value"] == 0.5           # A hits top, B does not
    assert card["frame@5"]["value"] == 1.0           # both have the true frame among blamed
    assert card["file@1"]["value"] == 0.5            # A's F.java basename matches; B's X.java does not
    assert card["n"] == 2


def test_none_extraction_scores_zero():
    recs = [FaultLocRecord("Z", None, [], None, "NONE")]
    card = grade_fault_localization(recs, oracle_by_case={"Z": {"fault_frame": "a.B.c", "fault_file": "a/B.java"}}, k=5)
    assert card["frame@1"]["value"] == 0.0 and card["no_fault_found"] == 1

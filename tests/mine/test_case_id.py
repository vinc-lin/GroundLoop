import json
import re
from pathlib import Path

from groundloop.mine.gh_miner import mine
from tests.mine.conftest import _node, _fake, _PRODFILE


def test_case_id_is_opaque_no_owner_leak(tmp_path):
    gh = _fake([_node(100, body="java.lang.IllegalStateException at app.A.f(A.java:5)",
                      closer={"slug": "TeamNewPipe/NewPipe", "files": [_PRODFILE]})])
    mine(["TeamNewPipe/NewPipe"], str(tmp_path), gh=gh, repo_name="newpipe",
         fleet_names=["newpipe", "osmand", "media3"], limit=5)
    dirs = [p for p in Path(tmp_path).iterdir() if p.is_dir()]
    assert dirs, "expected at least one emitted case"
    for d in dirs:
        assert re.match(r"^gl-[0-9a-f]{12}$", d.name), f"case dir not opaque: {d.name}"
        assert "newpipe" not in d.name
        assert "newpipe" not in (d / "ticket.json").read_text()          # invariant #2 over mined output
        assert json.loads((d / "_oracle" / "oracle.json").read_text())["owning_repo"] == "newpipe"  # mapping preserved

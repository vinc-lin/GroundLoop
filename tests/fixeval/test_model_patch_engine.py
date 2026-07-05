from groundloop.adapters.fix.model_patch import ModelPatchEngine
from groundloop.adapters.mock.model import CannedModel
from groundloop.core.types import Ticket, WorkTree, RepoRef

GOLD = "```diff\n--- a/x/A.cpp\n+++ b/x/A.cpp\n@@ -1 +1 @@\n-// bug\n+int nativeCreateHandler(){return 1;}\n```"


def test_propose_extracts_patch_from_model(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "A.cpp").write_text("// bug\n")
    eng = ModelPatchEngine(CannedModel({"default": GOLD}))
    patch = eng.propose(WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d"), ["x/A.cpp"])
    assert patch.files == ("x/A.cpp",) and "nativeCreateHandler" in patch.diff


def test_propose_empty_model_output_is_abstain(tmp_path):
    eng = ModelPatchEngine(CannedModel({"default": ""}))
    patch = eng.propose(WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d"), [])
    assert patch.diff == "" and patch.files == ()

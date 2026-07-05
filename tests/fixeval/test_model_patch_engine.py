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


class _CapturingModel:
    def __init__(self):
        self.prompt = None

    def complete(self, prompt: str) -> str:
        self.prompt = prompt
        return ""


def test_preamble_is_prepended_to_prompt(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "A.cpp").write_text("// bug\n")
    cap = _CapturingModel()
    eng = ModelPatchEngine(cap).with_preamble("\n\n# Applicable playbooks\n## Skill: s\ndo it")
    eng.propose(WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d"), ["x/A.cpp"])
    assert cap.prompt.startswith("\n\n# Applicable playbooks")
    assert "Bug: s" in cap.prompt


def test_empty_preamble_is_noop(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "A.cpp").write_text("// bug\n")
    cap_off, cap_on = _CapturingModel(), _CapturingModel()
    wt, tk = WorkTree(RepoRef("r"), str(tmp_path)), Ticket(id="t", summary="s", description="d")
    ModelPatchEngine(cap_off).propose(wt, tk, ["x/A.cpp"])
    ModelPatchEngine(cap_on, preamble="").propose(wt, tk, ["x/A.cpp"])
    assert cap_off.prompt == cap_on.prompt   # empty preamble => byte-identical prompt


def test_with_preamble_shares_model_for_cost():
    m = CannedModel({"default": ""})
    base = ModelPatchEngine(m)
    assert base.with_preamble("p").model is m   # cost accrues on the shared model instance

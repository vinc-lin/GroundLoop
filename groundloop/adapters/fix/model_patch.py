"""Real PROPOSE-PATCH FixEngine: reads @base snippets from the work-tree, asks the Model for a
unified diff, extracts it. Hermetic via CannedModel; live via GatewayModel. Satisfies core FixEngine."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from groundloop.core.types import Patch, Ticket, WorkTree
from groundloop.fixeval.patch import extract_unified_diff, touched_files


class ModelPatchEngine:
    def __init__(self, model):
        self.model = model

    def _snippet(self, wt_path: str, loc: str, max_lines: int = 40) -> str:
        p = Path(wt_path) / loc
        if not p.is_file():
            return ""
        return f"### {loc}\n" + "\n".join(p.read_text(errors="replace").splitlines()[:max_lines])

    def propose(self, worktree: WorkTree, ticket: Ticket, locations: Sequence[str]) -> Patch:
        snippets = "\n\n".join(self._snippet(worktree.path, loc) for loc in locations)
        prompt = (f"Bug: {ticket.summary}\n{ticket.description}\n\n"
                  f"Candidate files:\n{snippets}\n\n"
                  "Reply ONLY with a unified diff (```diff fenced) that fixes the bug, or empty if you cannot.")
        diff = extract_unified_diff(self.model.complete(prompt) or "")
        return Patch(diff=diff, files=tuple(touched_files(diff)))

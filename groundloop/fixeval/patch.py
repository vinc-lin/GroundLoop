"""Back-compat shim — the patch primitives moved to groundloop.fix.patch (Core-neutral). Kept so the
Dev-Labs fixeval stack + its tests import unchanged. See docs/superpowers/plans/2026-07-13-production-core-defaults-and-loop-closure.md."""
from groundloop.fix.patch import *  # noqa: F401,F403
from groundloop.fix.patch import (norm_path, extract_unified_diff, touched_files, patch_applies,  # noqa: F401
                                  added_lines, references_api, references_api_code, code_added_lines)

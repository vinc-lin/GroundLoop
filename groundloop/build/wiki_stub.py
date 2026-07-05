"""Make a wiki dir indexable when produce didn't finalize it — so `gloop index` can build a
SYMBOL-ONLY atlas (CBM symbols + bge-m3, no doc units) without a produced wiki.
See docs/type2-atlas-build-findings.md Finding 2."""
from __future__ import annotations

import glob
import json
import os


def ensure_indexable_wiki(wiki_dir: str) -> bool:
    """If <wiki_dir> lacks metadata.json, write a minimal valid wiki so load_wiki() succeeds:
    module_tree.json ({} if absent) + metadata.json listing any existing *.md as files_generated
    (salvages partial produce docs). Idempotent — returns True if it wrote a stub, False if a real
    metadata.json already exists (never clobbers a produced wiki)."""
    meta = os.path.join(wiki_dir, "metadata.json")
    if os.path.isfile(meta):
        return False
    os.makedirs(wiki_dir, exist_ok=True)
    tree = os.path.join(wiki_dir, "module_tree.json")
    if not os.path.isfile(tree):
        with open(tree, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
    mds = sorted(os.path.basename(p) for p in glob.glob(os.path.join(wiki_dir, "*.md")))
    with open(meta, "w", encoding="utf-8") as fh:
        json.dump({"files_generated": mds}, fh)
    return True

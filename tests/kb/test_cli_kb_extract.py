"""`gloop kb-extract` composition-root wrapper: LLM-propose (scripted CannedModel) -> tolerant parse ->
ground-check -> claims.json. Hermetic — monkeypatches the model + resolver SEAMS (cli._extract_model /
cli._extract_resolver) so no network / no real atlas is touched; exercises the real extract_to_store +
check_claim_grounded + claims.json write path over a 1-skill feedstock corpus."""
import json

import pytest

import groundloop.cli as cli
from groundloop.adapters.mock.model import CannedModel
from groundloop.engines.atlas.store import Store
from groundloop.kb.claim import load_claims

_SEED = '''
[[skill]]
id = "native-null-deref-segv"
provenance = "authored"
guidance = """
Signature: SIGSEGV tombstone.
Localize: the native translation unit.
Fix: guard the nativePtr handle.
"""

[skill.match]
any_text = ["sigsegv"]
'''

_RESPONSE = json.dumps({"claims": [
    {"type": "fix_step",
     "content": "Reject a 0 nativePtr handle at native method entry before dereferencing it.",
     "grounding_refs": ["GetLongField"], "applies_when": {"any_text": ["sigsegv"]}}]})


def test_kb_extract_writes_grounded_candidates(tmp_path, monkeypatch):
    seed = tmp_path / "feedstock.toml"
    seed.write_text(_SEED)
    out = tmp_path / "claims.json"

    monkeypatch.setattr(cli, "_extract_model", lambda: CannedModel({"default": _RESPONSE}))
    monkeypatch.setattr(cli, "_extract_resolver", lambda db: (lambda ref: ref == "GetLongField"))

    rc = cli.main(["kb-extract", "--skills-seed", str(seed), "--index-db", "unused.db", "--out", str(out)])
    assert rc == 0
    store = load_claims(str(out))
    assert len(store) == 1
    (claim,) = store.values()
    assert claim.tier == "candidate"
    assert claim.type == "fix_step"
    assert claim.grounding_refs == ("GetLongField",)
    assert claim.provenance == "native-null-deref-segv"


def test_kb_extract_drops_hallucinated_ref(tmp_path, monkeypatch):
    seed = tmp_path / "feedstock.toml"
    seed.write_text(_SEED)
    out = tmp_path / "claims.json"

    monkeypatch.setattr(cli, "_extract_model", lambda: CannedModel({"default": _RESPONSE}))
    monkeypatch.setattr(cli, "_extract_resolver", lambda db: (lambda ref: False))   # nothing resolves

    rc = cli.main(["kb-extract", "--skills-seed", str(seed), "--index-db", "unused.db", "--out", str(out)])
    assert rc == 0
    assert load_claims(str(out)) == {}          # the sole candidate failed grounding -> store empty


def test_extract_resolver_fails_fast_on_empty_atlas(tmp_path):
    """A wrong/typo'd --index-db yields a 0-unit atlas; the resolver seam errors loudly instead of
    silently rejecting every ref (which would misleadingly print 'N rejected' + exit 0)."""
    empty_db = tmp_path / "empty.db"
    Store(str(empty_db))                         # creates the schema, indexes nothing
    with pytest.raises(SystemExit) as ei:
        cli._extract_resolver(str(empty_db))
    assert "0 indexed units" in str(ei.value)

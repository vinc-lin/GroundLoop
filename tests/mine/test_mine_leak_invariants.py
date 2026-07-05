import json
from pathlib import Path

from groundloop.adapters.mock.jira import MockJira
from groundloop.domains.android_ivi.owner_tokens import owner_tokens_for
from groundloop.domains.android_ivi.signal_extractor import AndroidSignalExtractor
from groundloop.mine.gh_miner import mine
from tests.mine.conftest import _node, _fake, _PRODFILE

OWNER = "newpipe"
FLEET = ["newpipe", "osmand", "media3", "cameraview"]


def _norm(s: str) -> str:
    return (s.lower().replace(" ", "").replace("-", "").replace("_", "")
            .replace(".", "").replace("/", ""))


def _needles():
    row = owner_tokens_for(OWNER)
    return {_norm(t) for t in (list(row["slugs"]) + list(row["namespaces"]) + [OWNER]) if _norm(t)}


def _fake_gh():
    # a newpipe issue leaking the owner via namespace + GitHub org + bare slug — all forms T1-T4 redact.
    body = ("Dup of https://github.com/TeamNewPipe/NewPipe/issues/900 . NewPipe crashes on search.\n"
            "```\njava.lang.NullPointerException\n"
            "  at org.schabi.newpipe.SearchFragment.doSearch(SearchFragment.java:42)\n```")
    return _fake([_node(4242, title="NewPipe search crash", body=body,
                        closer={"slug": "TeamNewPipe/NewPipe", "files": [_PRODFILE]})])


def _mine(tmp_path):
    out = str(tmp_path / "ds")
    mine(["TeamNewPipe/NewPipe"], out, gh=_fake_gh(), repo_name=OWNER, fleet_names=FLEET, limit=5)
    return [p for p in Path(out).iterdir() if p.is_dir()]


def test_mine_admits_the_adversarial_case(tmp_path):
    assert _mine(tmp_path), "non-vacuity: the scrubbed case must still admit (generic signal survives)"


def test_mined_case_id_and_dir_are_opaque(tmp_path):
    needles = {_norm(n) for n in FLEET}
    for d in _mine(tmp_path):
        assert not any(n in _norm(d.name) for n in needles)
        assert not any(n in _norm(json.loads((d / "ticket.json").read_text())["id"]) for n in needles)


def test_no_owner_token_in_loop_visible_fields(tmp_path):
    needles = _needles()
    for d in _mine(tmp_path):
        raw = json.loads((d / "ticket.json").read_text())
        hay = _norm(raw.get("summary", "") + raw.get("description", "") + raw.get("component", ""))
        for lg in (d / "logs").glob("*.txt"):
            hay += _norm(lg.read_text())
        assert not any(n in hay for n in needles), f"owner token survived in {d.name}"


def test_extractor_over_emitted_ticket_yields_no_owner_tokens(tmp_path):
    needles = _needles()
    root = str(Path(tmp_path) / "ds")
    for d in _mine(tmp_path):
        ticket = MockJira(root).fetch(d.name)
        sig = AndroidSignalExtractor().extract(ticket.logs, ticket)
        assert not any(any(n in _norm(t) for n in needles) for t in sig.tokens()), \
            f"owner token reached the matcher for {d.name}"


def test_no_hidden_oracle_key_is_loop_visible(tmp_path):
    for d in _mine(tmp_path):
        tj = (d / "ticket.json").read_text()
        for hidden in ("is_answerable", "negative_class", "held_out_repo", "owning_repo"):
            assert hidden not in tj

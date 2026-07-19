from groundloop.mine.gh_miner import admit_e2e
from groundloop.mine.harvest import Candidate
from groundloop.mine.signal import has_crash_signature

_STACK = """Fatal Exception: java.lang.IllegalStateException: bad state
    at com.example.player.Decoder.init(Decoder.java:88)
    at com.example.player.Player.start(Player.java:42)"""
_NATIVE = "#00 pc 0001a2b4  /system/lib64/libplayer.so (Decoder::feed(char const*)+44)"
_LOGCAT = "E AudioTrack: AudioFlinger could not create track, status: -12"
_PROSE = "The settings screen should remember my sort order between launches. It doesn't."

_PRODFILE = [{"filename": "src/main/java/app/A.java", "status": "modified"}]


def test_crash_signatures_detected():
    assert has_crash_signature(_STACK)
    assert has_crash_signature(_NATIVE)
    assert has_crash_signature(_LOGCAT)


def test_prose_rejected():
    assert not has_crash_signature(_PROSE)
    assert not has_crash_signature("")


def test_sentence_prose_not_mistaken_for_logcat():
    # "I"/"E"/... + a single word + colon is sentence-y prose, not a logcat tag line.
    assert not has_crash_signature("I think: this is broken.")
    assert not has_crash_signature("I expected: a value")
    assert not has_crash_signature("I have: nothing")
    # real logcat tags (slash form + uppercase space form) still fire
    assert has_crash_signature("E AudioTrack: could not create track")
    assert has_crash_signature("E/AudioTrack( 1234): boom")
    assert has_crash_signature("W System: low memory")


def _candidate(body: str, *, merge_commit_sha: str = "sha1", files=None) -> Candidate:
    return Candidate(
        owning_slug="owner/repo", issue_number=1, issue_title="t", issue_body=body, issue_url="u",
        labels=(), created_at="2026-01-01T00:00:00Z", pr_number=2,
        merge_commit_sha=merge_commit_sha, merged_at="2026-01-02T00:00:00Z", files_total=len(files or []),
        files=files or [])


def test_admit_e2e_crash_body_and_merged_fix_admits():
    cand = _candidate(_STACK, files=_PRODFILE)
    assert admit_e2e(cand, require_crash_log=True, require_merged_fix=True)


def test_admit_e2e_prose_rejected_under_require_crash_log():
    cand = _candidate(_PROSE, files=_PRODFILE)
    assert not admit_e2e(cand, require_crash_log=True, require_merged_fix=False)


def test_admit_e2e_no_merged_fix_rejected_under_require_merged_fix():
    cand = _candidate(_STACK, merge_commit_sha="", files=[])
    assert not admit_e2e(cand, require_crash_log=False, require_merged_fix=True)


def test_admit_e2e_both_flags_off_admits_regardless():
    cand = _candidate(_PROSE, merge_commit_sha="", files=[])
    assert admit_e2e(cand, require_crash_log=False, require_merged_fix=False)

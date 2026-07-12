import tomllib
from pathlib import Path
import random
from groundloop.synth.logs import CRASH_CLASSES, Frame

_SEED = Path("groundloop/kb/data/aaos_kb_seed.toml")


def _guidance_by_skill():
    data = tomllib.loads(_SEED.read_text())
    return {s["id"]: s.get("guidance", "").lower() for s in data["skill"]}


def _sample_log(cc) -> str:
    frames = [Frame(package="com.x", cls="Foo", method="bar", filename="Foo.java", line=42)]
    rng = random.Random(0)
    out = cc.builder("libx.so", frames, rng) if cc.surface == "native" else cc.builder(frames, rng)
    return out.lower()


def test_planted_api_is_in_guidance_and_headroom_clean():
    guidance = _guidance_by_skill()
    gradeable = [c for c in CRASH_CLASSES if c.required_api]
    assert len(gradeable) >= 4, "need a non-trivial gradeable subset"
    for cc in gradeable:
        api = cc.required_api.lower()
        # (a) the KB arm actually receives it: the API is named in the skill's rendered guidance
        assert api in guidance.get(cc.skill_id, ""), f"{cc.skill_id}: '{api}' not in skill guidance"
        # (b) headroom: the API must NOT already appear in this class's own crash log
        assert api not in _sample_log(cc), f"{cc.skill_id}: required_api leaks into its own log"

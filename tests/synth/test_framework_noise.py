import random
import re
from groundloop.synth.data.framework_noise import render_noise_lines, FLEET_OWNER_HINTS


def test_render_is_deterministic_and_long():
    a = render_noise_lines(random.Random(7), n=200, base_ms=0)
    b = render_noise_lines(random.Random(7), n=200, base_ms=0)
    assert a == b and len(a) == 200


def test_lines_are_logcat_shaped():
    pat = re.compile(r"\d\d-\d\d \d\d:\d\d:\d\d\.\d\d\d\s+\d+\s+\d+ [EWIDF] \w+: ")
    for ln in render_noise_lines(random.Random(1), n=50, base_ms=0):
        assert pat.match(ln), ln


def test_noise_excludes_owner_tokens():
    text = "\n".join(render_noise_lines(random.Random(3), n=500, base_ms=0))
    for owner_tok in ("net.osmand", "org.schabi.newpipe", "liboboe.so", "com.google.oboe"):
        assert owner_tok not in text
    assert isinstance(FLEET_OWNER_HINTS, frozenset)

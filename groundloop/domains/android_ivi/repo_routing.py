"""Production-known namespace/SONAME -> repo routing (Android Log Match v2 §7.1). ANTI-LEAK: derived ONLY
from each repo's declared package namespaces + library names (the estate-manifest knowledge a triage
engineer has); it reads NO per-case oracle and is global/case-independent. Provenance: OSS-proxy fleet
manifests (build.gradle applicationId / AndroidManifest package / CMake library name)."""
from __future__ import annotations

from groundloop.core.types import Signals

# prefix -> repo. Longest-prefix wins. Provenance in the module docstring above.
ROUTES: dict[str, str] = {
    "net.osmand": "osmand",
    "app.organicmaps": "organicmaps",
    "org.schabi.newpipe": "newpipe",
    "de.danoeh.antennapod": "antennapod",
    "com.google.oboe": "oboe",
    "org.wysaid": "android-gpuimage-plus",
    "com.otaliastudios.cameraview": "cameraview",
    "androidx.media3": "media3",
}
SONAMES: dict[str, str] = {
    "liboboe.so": "oboe",
    "libdlt.so": "dlt-daemon",
    "libCGE.so": "android-gpuimage-plus",
}


def _route_prefix(pkg: str) -> str | None:
    best = None
    for pref, repo in ROUTES.items():
        if (pkg == pref or pkg.startswith(pref + ".")) and (best is None or len(pref) > len(best[0])):
            best = (pref, repo)
    return best[1] if best else None


def route_signals(signals: Signals) -> list[tuple[str, float]]:
    """Map fault-site signal tokens to owning repos. Returns [(repo, weight)] deduped, weight=1.0."""
    hits: dict[str, float] = {}
    for pkg in signals.packages + signals.classes:
        repo = _route_prefix(pkg)
        if repo:
            hits[repo] = 1.0
    for so in signals.libraries:
        repo = SONAMES.get(so)
        if repo:
            hits[repo] = 1.0
    return list(hits.items())

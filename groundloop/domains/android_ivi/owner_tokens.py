"""Per-repo owner-identifying token table for the Type-2 leak-scrubber (docs/type2-evaluation.md §4.3).

The scrubber is PER-CASE: a repo's tokens are redacted only when it is that case's owning_repo.
`androidx.media3` is owner-identifying for media3 yet a KEPT dependency signal for antennapod/newpipe.
"""
from __future__ import annotations

FLEET_OWNER_TOKENS: dict[str, dict] = {
    "osmand": {
        "namespaces": ["net.osmand"], "slugs": ["osmand", "osmandapp", "OsmAnd"],
        "sonames": ["libOsmAndCore.so", "libOsmAndCoreWithJNI.so", "libosmand.so"],
        "KEEP": ["android.", "androidx.", "java.", "kotlin.", "libc.so", "libGLESv2.so"],
    },
    "organicmaps": {
        "namespaces": ["app.organicmaps", "com.mapswithme"],  # com.mapswithme = historical alias
        "slugs": ["organicmaps", "OrganicMaps", "MapsWithMe", "mapswithme"],
        "sonames": ["liborganicmaps.so"],
        "KEEP": ["android.", "androidx.", "java.", "libc.so", "libGLESv2.so", "libjnigraphics.so"],
    },
    "antennapod": {
        "namespaces": ["de.danoeh.antennapod", "de.danoeh"],
        "slugs": ["antennapod", "AntennaPod", "danoeh"], "sonames": [],
        "KEEP": ["android.", "androidx.", "androidx.media3.", "android.media.", "java.", "kotlin."],
    },
    "newpipe": {
        "namespaces": ["org.schabi.newpipe", "org.schabi"],
        "slugs": ["newpipe", "NewPipe", "schabi"], "sonames": [],
        "KEEP": ["android.", "androidx.", "androidx.media3.", "java.", "kotlin."],
    },
    "oboe": {
        "namespaces": ["oboe::"], "slugs": ["oboe", "Oboe"], "sonames": ["liboboe.so"],
        "KEEP": ["libaaudio.so", "libOpenSLES.so", "android.media.AudioTrack", "libc.so"],
    },
    "cameraview": {
        "namespaces": ["com.otaliastudios.cameraview", "com.otaliastudios"],
        "slugs": ["otaliastudios", "natario1"],  # bare 'cameraview' is a generic word — redact via namespace only
        "sonames": [],
        "KEEP": ["androidx.camera.", "android.hardware.camera2.", "android.graphics.SurfaceTexture", "android."],
    },
    "dlt-daemon": {
        "namespaces": ["dlt_"], "slugs": ["dlt-daemon", "dlt", "COVESA", "GENIVI", "genivi"],
        "sonames": ["libdlt.so"], "KEEP": ["libc.so", "syslog", "libpthread.so"],
    },
    "media3": {
        "namespaces": ["androidx.media3", "com.google.android.exoplayer2"],  # exoplayer2 = pre-donation alias
        "slugs": ["media3", "ExoPlayer", "exoplayer"],
        "sonames": ["libexoplayerflac.so", "libmedia3.so"],
        "KEEP": ["android.media.", "androidx.media.", "androidx.core.", "android.", "java."],
    },
    "android-gpuimage-plus": {
        "namespaces": ["org.wysaid"], "slugs": ["wysaid", "android-gpuimage-plus", "gpuimage", "CGE", "cge"],
        "sonames": ["libCGE.so", "libCGE_java", "libcge.so"],
        "KEEP": ["libffmpeg.so", "java.lang.UnsatisfiedLinkError", "android.opengl.", "libGLESv2.so", "libEGL.so"],
    },
}


def owner_tokens_for(repo: str) -> dict:
    """The owner-token row for a fleet repo. Raises KeyError for an unknown repo."""
    return FLEET_OWNER_TOKENS[repo]

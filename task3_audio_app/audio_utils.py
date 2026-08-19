"""
Audio metadata extraction for Task 3 submissions - duration, sample rate,
bitrate, loudness (dBFS), and a rule-based quality/noise estimate (bonus).

Operates on a file already saved to disk (not raw bytes), so the same path
can be read by both pydub (duration/sample rate/loudness - it decodes via
ffmpeg, so WAV/MP3/WEBM-Opus/OGG all work uniformly) and ffprobe (the true
container bitrate, which isn't derivable from sample rate for compressed
formats like MP3/WEBM the way it is for uncompressed WAV).
"""

import json
import subprocess

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

# Whole-clip average loudness below this -> "silent" (the person mostly
# didn't speak, or the mic barely picked anything up). Calibrated against 5
# real test recordings: a deliberately mostly-silent clip averaged -35.4
# dBFS while 4 normal-speech clips ranged -23 to -28 dBFS - a clear ~8dB
# gap, so -30 sits cleanly between them.
OVERALL_SILENCE_DBFS = -30.0
# Peak-to-average gap (crest factor) below this -> flat/compressed loudness
# profile -> "noisy" (constant background noise/hum has little dynamic
# range; natural speech has a lot). The 5 real clean-speech samples all
# measured 16.5-34.1, so 15.0 sits below all of them - but there's no
# genuinely noisy sample to calibrate against yet, worth re-testing against
# one deliberately (e.g. recording next to a fan or with a TV on).
CREST_FACTOR_FOR_NOISY_LABEL = 15.0
WINDOW_MS = 100


class UnsupportedAudioError(Exception):
    """Raised when the saved file can't be decoded as audio at all."""


def extract_metadata(path):
    try:
        audio = AudioSegment.from_file(path)
    except CouldntDecodeError as exc:
        raise UnsupportedAudioError(str(exc)) from exc

    if len(audio) == 0:
        raise UnsupportedAudioError("Recording is empty (0 duration).")

    loudness_dbfs = audio.dBFS
    if loudness_dbfs == float("-inf"):
        # True digital silence - pydub returns -inf here, which SQLite can
        # store but which breaks normal comparisons/display. Clamp to a
        # documented sentinel floor instead of writing -inf.
        loudness_dbfs = -100.0

    return {
        "audio_format": path.suffix.lstrip(".").lower(),
        "duration_sec": round(audio.duration_seconds, 3),
        "sample_rate_hz": audio.frame_rate,
        "bitrate_kbps": round(_read_bitrate_kbps(path), 1),
        "loudness_dbfs": round(loudness_dbfs, 1),
        "quality_label": _estimate_quality(audio),
    }


def _read_bitrate_kbps(path):
    """Real encoded bitrate via ffprobe (bundled with ffmpeg). A compressed
    codec's bitrate is a setting it was encoded at, not something you can
    back out from sample_rate * bit_depth the way you can for raw WAV -
    so we read what the container actually reports instead of guessing.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(result.stdout)
    return int(info["format"]["bit_rate"]) / 1000


def _estimate_quality(audio):
    """Rule-based quality/noise estimate (Task 3 bonus): whole-clip average
    loudness for "silent", crest factor for "noisy". Deliberately simple
    and explainable - measured properties, not an unexplainable model.

    Known limitation, stated plainly: this does NOT detect unclear/mumbled
    speech - that's a frequency-domain question (spectral clarity), and a
    loudness-based heuristic has no way to see it. "noisy" here specifically
    means "flat, low-dynamic-range loudness profile" (constant background
    hum/static), not "hard to understand."
    """
    if audio.dBFS == float("-inf") or audio.dBFS < OVERALL_SILENCE_DBFS:
        return "silent"

    windows = [audio[i:i + WINDOW_MS] for i in range(0, len(audio), WINDOW_MS)]
    voiced_levels = [w.dBFS for w in windows if w.dBFS != float("-inf")]
    if not voiced_levels:
        return "silent"

    crest_factor = max(voiced_levels) - (sum(voiced_levels) / len(voiced_levels))
    return "noisy" if crest_factor < CREST_FACTOR_FOR_NOISY_LABEL else "good"

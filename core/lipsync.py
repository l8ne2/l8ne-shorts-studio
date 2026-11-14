"""Synchronisation labiale simple : ouverture de la bouche d'après le volume de la voix."""
import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 16000


class LipSyncError(Exception):
    """Erreur lors de l'analyse de l'audio."""


def audio_envelope(audio_path, fps: int = 30, ffmpeg: str = None, runner=subprocess.run) -> np.ndarray:
    """Volume (0 à ~1) de la voix pour chaque image vidéo."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise LipSyncError("FFmpeg introuvable.")
    result = runner([ffmpeg, "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1",
                     "-ar", str(SAMPLE_RATE), "-"], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise LipSyncError("Audio illisible : régénère la voix.")
    samples = np.frombuffer(result.stdout, dtype=np.int16).astype("float32") / 32768.0
    hop = SAMPLE_RATE // fps
    n = len(samples) // hop
    if n == 0:
        raise LipSyncError("Audio trop court.")
    rms = np.sqrt((samples[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    ref = np.percentile(rms, 95) or 1.0
    return rms / ref


def mouth_levels(envelope: np.ndarray, thresholds=(0.18, 0.45, 0.75)) -> list:
    """Niveau d'ouverture (0 fermée ... 3 grande ouverte) par image, sans clignotement."""
    env = np.convolve(envelope, np.ones(3) / 3, mode="same")
    levels = np.digitize(env, thresholds)
    out = levels.copy()
    for i in range(1, len(levels) - 1):  # supprime les pics isolés d'une seule image
        if levels[i] != levels[i - 1] and levels[i] != levels[i + 1]:
            out[i] = levels[i - 1]
    return [int(v) for v in out]


def gesture_levels(envelope: np.ndarray, fps: int = 30) -> list:
    """Intensité de la voix sur ~0,6 s : 0 (calme), 1, 2 (emphase) — pilote les gestes du bras."""
    win = max(1, int(fps * 0.6))
    avg = np.convolve(envelope, np.ones(win) / win, mode="same")
    return [int(v) for v in np.digitize(avg, (0.45, 0.7))]

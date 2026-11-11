"""Narration audio avec Edge TTS (Phase 2).

Produit un MP3 et la liste des mots avec leur horodatage, utilisée plus tard
pour synchroniser les sous-titres.
"""
import asyncio
import json
import os
from pathlib import Path

from core.config import ROOT

AUDIO_DIR = ROOT / "media" / "audio"
DEFAULT_VOICE = "fr-FR-HenriNeural"
TICKS_PER_SECOND = 10_000_000  # Edge TTS exprime les durées en unités de 100 ns


class VoiceGenerationError(Exception):
    """Erreur lors de la génération de la voix (réseau, texte vide, service...)."""


async def _synthesize(text, voice, rate, audio_path, communicate_cls):
    try:
        comm = communicate_cls(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # anciennes versions d'edge-tts sans paramètre boundary
        comm = communicate_cls(text, voice, rate=rate)
    words, size = [], 0
    with open(audio_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
                size += len(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                start = chunk["offset"] / TICKS_PER_SECOND
                words.append(
                    {
                        "text": chunk["text"],
                        "start": round(start, 3),
                        "end": round(start + chunk["duration"] / TICKS_PER_SECOND, 3),
                        "kind": chunk["type"],
                    }
                )
    return words, size


def generate_voice(text: str, channel_cfg: dict, project_id: int, audio_dir=None, communicate_cls=None) -> dict:
    """Génère media/audio/project_<id>.mp3 et son fichier d'horodatage .words.json.

    Écrit d'abord dans un fichier .part, renommé seulement en cas de succès :
    un échec ne laisse jamais de MP3 corrompu.
    """
    if not text.strip():
        raise VoiceGenerationError("Le script est vide.")
    if communicate_cls is None:
        import edge_tts  # import tardif : inutile pour les tests

        communicate_cls = edge_tts.Communicate

    voice_cfg = channel_cfg.get("voice", {})
    voice = voice_cfg.get("name", DEFAULT_VOICE)
    rate = voice_cfg.get("rate", "+0%")

    audio_dir = Path(audio_dir or AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"project_{project_id}.mp3"
    words_path = audio_dir / f"project_{project_id}.words.json"
    part_path = audio_path.with_suffix(".mp3.part")

    try:
        words, size = asyncio.run(_synthesize(text, voice, rate, part_path, communicate_cls))
        if size == 0:
            raise VoiceGenerationError("Aucun audio reçu d'Edge TTS.")
        os.replace(part_path, audio_path)
    except VoiceGenerationError:
        part_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # réseau, service indisponible, voix inconnue...
        part_path.unlink(missing_ok=True)
        raise VoiceGenerationError(f"Edge TTS a échoué : {exc}") from exc

    words_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    duration = max((w["end"] for w in words), default=None)
    return {"audio_path": audio_path, "words_path": words_path, "duration": duration, "voice": voice}

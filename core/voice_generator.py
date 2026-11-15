"""Narration audio avec Edge TTS (Phase 2).

Produit un MP3 et la liste des mots avec leur horodatage, utilisée plus tard
pour synchroniser les sous-titres.
"""
import asyncio
import json
import os
import shutil
import subprocess
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


def compute_cuts(words: list, cap: float = 0.22, lead: float = 0.12) -> list:
    """Zones de silence à supprimer : [(début, fin), ...] en secondes de l'audio d'origine.

    Chaque pause plus longue que `cap` est réduite à `cap` ; le silence au tout début est réduit à `lead`.
    """
    cuts = []
    if words and words[0]["start"] > lead + 0.05:
        cuts.append((0.0, words[0]["start"] - lead))
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > cap + 0.05:
            cuts.append((a["end"] + cap / 2, b["start"] - cap / 2))
    return cuts


def shift_words(words: list, cuts: list) -> list:
    """Recale les horodatages une fois les silences supprimés."""
    def shift(t):
        return t - sum(min(max(t - c0, 0.0), c1 - c0) for c0, c1 in cuts)
    return [{**w, "start": round(shift(w["start"]), 3), "end": round(shift(w["end"]), 3)} for w in words]


def tighten_pauses(audio_path, words: list, cap: float = 0.22, ffmpeg: str = None, runner=subprocess.run):
    """Raccourcit les pauses trop longues de la voix. Retourne (mots_recalés, modifié).

    N'échoue jamais : si FFmpeg est absent ou échoue, l'audio d'origine est conservé.
    """
    cuts = compute_cuts(words, cap)
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not cuts or not ffmpeg:
        return words, False
    audio_path = Path(audio_path)
    bounds = [0.0] + [t for c in cuts for t in c]
    segments = [(bounds[i], bounds[i + 1] if i + 1 < len(bounds) else None) for i in range(0, len(bounds), 2)]
    segments = [(a, b) for a, b in segments if b is None or b - a > 0.01]
    parts, labels = [], []
    for i, (a, b) in enumerate(segments):
        trim = f"start={a:.3f}" + (f":end={b:.3f}" if b is not None else "")
        parts.append(f"[0:a]atrim={trim},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]"
    tmp = audio_path.with_name(audio_path.stem + ".tight.mp3")
    try:
        result = runner([ffmpeg, "-y", "-loglevel", "error", "-i", str(audio_path), "-filter_complex", graph,
                         "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "3", str(tmp)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            return words, False
        os.replace(tmp, audio_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        return words, False
    return shift_words(words, cuts), True


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

    if voice_cfg.get("tighten", True):
        words, _ = tighten_pauses(audio_path, words, cap=float(voice_cfg.get("pause", 0.22)))
    words_path.write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
    duration = max((w["end"] for w in words), default=None)
    return {"audio_path": audio_path, "words_path": words_path, "duration": duration, "voice": voice}


def generate_dialogue_voice(lines: list, speakers: list, project_id: int, rate: str = "+0%", audio_dir=None,
                            gap: float = 0.18, pause_cap: float = 0.22, communicate_cls=None,
                            ffmpeg: str = None, runner=subprocess.run) -> dict:
    """Génère la voix d'un dialogue : une voix par personnage, réplique par réplique, puis assemblage.

    lines : [(index_du_personnage, réplique)] ; speakers : [{'name', 'voice', ...}, ...].
    Écrit project_<id>.mp3, project_<id>.words.json (mots horodatés + personnage) et
    project_<id>.segments.json (qui parle de quand à quand). Retourne un dict avec les chemins.
    """
    from core.video_editor import probe_duration  # import tardif : évite une dépendance circulaire

    if not lines:
        raise VoiceGenerationError("Le dialogue est vide.")
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise VoiceGenerationError("FFmpeg est nécessaire pour assembler les voix du dialogue.")
    if communicate_cls is None:
        import edge_tts

        communicate_cls = edge_tts.Communicate

    audio_dir = Path(audio_dir or AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)
    seg_files, segments, all_words = [], [], []
    offset = 0.0
    try:
        for i, (spk, text) in enumerate(lines):
            voice = speakers[spk].get("voice") or DEFAULT_VOICE
            seg_path = audio_dir / f"project_{project_id}_seg{i}.mp3"
            seg_files.append(seg_path)
            try:
                words, size = asyncio.run(_synthesize(text, voice, rate, seg_path, communicate_cls))
            except Exception as exc:
                raise VoiceGenerationError(f"Edge TTS a échoué (réplique {i + 1}, voix {voice}) : {exc}") from exc
            if size == 0:
                raise VoiceGenerationError(f"Aucun audio reçu pour la réplique {i + 1}.")
            words, _ = tighten_pauses(seg_path, words, cap=pause_cap, ffmpeg=ffmpeg, runner=runner)
            duration = probe_duration(seg_path, runner=runner) or (max((w["end"] for w in words), default=0.5) + 0.1)
            all_words += [{**w, "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3),
                           "speaker": spk} for w in words]
            segments.append({"speaker": spk, "text": text, "start": round(offset, 3),
                             "end": round(offset + duration, 3)})
            offset += duration + gap
        # assemblage : on ajoute `gap` secondes de silence après chaque réplique (sauf la dernière)
        inputs = [arg for f in seg_files for arg in ("-i", str(f))]
        parts = [f"[{i}:a]apad=pad_dur={gap}[a{i}]" if i < len(seg_files) - 1 else f"[{i}:a]anull[a{i}]"
                 for i in range(len(seg_files))]
        graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(seg_files))) + \
            f"concat=n={len(seg_files)}:v=0:a=1[out]"
        audio_path = audio_dir / f"project_{project_id}.mp3"
        tmp = audio_path.with_name(audio_path.stem + ".dlg.mp3")
        result = runner([ffmpeg, "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[out]",
                         "-c:a", "libmp3lame", "-q:a", "3", str(tmp)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise VoiceGenerationError(f"Assemblage des voix impossible : {(result.stderr or '')[-300:]}")
        os.replace(tmp, audio_path)
    finally:
        for f in seg_files:
            f.unlink(missing_ok=True)

    words_path = audio_dir / f"project_{project_id}.words.json"
    segments_path = audio_dir / f"project_{project_id}.segments.json"
    words_path.write_text(json.dumps(all_words, ensure_ascii=False, indent=1), encoding="utf-8")
    segments_path.write_text(json.dumps(segments, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"audio_path": audio_path, "words_path": words_path, "segments_path": segments_path,
            "duration": segments[-1]["end"], "segments": segments}

"""Orchestration du montage d'un Short à partir des assets enregistrés en base.

Les étapes amont (script, voix, visuels, sous-titres) sont déclenchées depuis l'interface ;
ici on assemble le tout. Un échec met le projet en ERROR avec le message, sans rien perdre :
on peut relancer le montage tel quel.
"""
import json
import re
import shutil
from pathlib import Path

from core.config import ROOT, load_channel
from core.animator import SceneSpec, render_scene
from core.lipsync import audio_envelope, gesture_levels, mouth_levels
from core.subtitle_generator import cue_params, to_ass, words_to_cues
from core.video_editor import (
    TAIL_SECONDS, VideoEditError, assemble_video, compute_scene_durations, probe_duration,
)
from database import db

OUTPUT_DIR = ROOT / "output"
LABEL_DELAY, LABEL_MAX = 0.25, 3.0  # une étiquette apparaît peu après le début de la scène, quelques secondes


def _asset_path(project_id: int, asset_type: str, db_path=None):
    for a in reversed(db.list_assets(project_id, asset_type, db_path=db_path)):
        if Path(a["file_path"]).exists():
            return Path(a["file_path"])
    return None


def missing_steps(project_id: int, db_path=None) -> list:
    """Étapes à terminer avant le montage (liste vide = prêt)."""
    labels = {"audio": "voix off", "timings": "voix off (horodatage)", "scenes": "visuels",
              "subtitles_ass": "sous-titres"}
    return [label for key, label in labels.items() if not _asset_path(project_id, key, db_path)]


def _scene_labels(plan: list, durations: list) -> list:
    labels, start = [], 0.0
    for entry, dur in zip(plan, durations):
        text = (entry.get("label") or "").strip()
        if text:
            begin = start + LABEL_DELAY
            end = min(start + dur, begin + LABEL_MAX)
            if end - begin > 0.4:
                labels.append({"start": begin, "end": end, "text": text})
        start += dur
    return labels


def _prepare_clips(plan: list, durations: list, audio, out: Path, ffmpeg: str = None):
    """Rend les scènes animées (personnage qui parle) ; les autres scènes gardent leur fichier d'origine."""
    animated = [i for i, e in enumerate(plan) if e.get("animation")]
    if not animated:
        return [e["file"] for e in plan], None
    ffmpeg = ffmpeg or shutil.which("ffmpeg") or "ffmpeg"
    envelope = audio_envelope(audio, ffmpeg=ffmpeg)
    mouths, gestures = mouth_levels(envelope), gesture_levels(envelope)
    anim_dir = out.parent / f".anim_{out.stem}"
    anim_dir.mkdir(parents=True, exist_ok=True)
    clips, start = [], 0.0
    for i, (entry, dur) in enumerate(zip(plan, durations)):
        anim = entry.get("animation")
        if anim:
            spec = SceneSpec(background=entry["file"], duration=dur, start_time=start, index=i,
                             emotion=entry.get("emotion", "neutral"), kind=anim["type"],
                             design=anim.get("design") or {}, sprite=entry.get("sprite"))
            clips.append(str(render_scene(spec, mouths, gestures, anim_dir / f"scene_{i + 1}.mp4", ffmpeg)))
        else:
            clips.append(entry["file"])
        start += dur
    return clips, anim_dir


def render_project(project_id: int, framing: str = "crop", db_path=None, output_dir=None, **editor_kwargs) -> dict:
    project = db.get_project(project_id, db_path)
    missing = missing_steps(project_id, db_path)
    if missing:
        raise VideoEditError("Étapes manquantes : " + ", ".join(dict.fromkeys(missing)) + ".")

    plan = json.loads(_asset_path(project_id, "scenes", db_path).read_text(encoding="utf-8"))
    words = json.loads(_asset_path(project_id, "timings", db_path).read_text(encoding="utf-8"))
    audio = _asset_path(project_id, "audio", db_path)
    ass = _asset_path(project_id, "subtitles_ass", db_path)

    db.set_status(project_id, "RENDERING", db_path=db_path)
    try:
        audio_duration = editor_kwargs.pop("audio_duration", None) or probe_duration(audio)
        durations = compute_scene_durations([s["text"] for s in plan], words, audio_duration)
        safe_title = re.sub(r"[^a-zA-Z0-9]+", "_", project["title"]).strip("_").lower() or "short"
        out = Path(output_dir or OUTPUT_DIR) / project["channel_slug"] / f"{safe_title}_{project_id}.mp4"
        labels = _scene_labels(plan, durations)
        if labels:  # étiquettes à l'écran : on régénère le .ass en y ajoutant les étiquettes
            style_name = load_channel(project["channel_slug"]).get("style", {}).get("subtitles", "modernes")
            ass_text = to_ass(words_to_cues(words, **cue_params(style_name)), style_name, labels)
            ass = ass.with_name(ass.stem + "_labels.ass")
            ass.write_text(ass_text, encoding="utf-8")
        clips, anim_dir = _prepare_clips(plan, durations, audio, out, editor_kwargs.get("ffmpeg"))
        try:
            result = assemble_video(clips, durations, audio, ass, out, framing=framing, **editor_kwargs)
        finally:
            if anim_dir:
                shutil.rmtree(anim_dir, ignore_errors=True)
    except Exception as exc:
        db.set_status(project_id, "ERROR", error=str(exc), db_path=db_path)
        raise
    final_duration = probe_duration(result) or sum(durations)
    db.add_export(project_id, result, round(final_duration), db_path=db_path)
    db.set_status(project_id, "COMPLETED", db_path=db_path)
    credits = "\n".join(dict.fromkeys(s.get("credit", "") for s in plan if s.get("credit")))
    return {"path": result, "duration": final_duration, "credits": credits}

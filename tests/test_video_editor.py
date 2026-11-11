import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from core.pipeline import missing_steps, render_project
from core.subtitle_generator import generate_subtitles
from core.video_editor import (
    VideoEditError, assemble_video, compute_scene_durations, probe_duration,
)
from database import db


def W(text, start, end):
    return {"text": text, "start": start, "end": end, "kind": "WordBoundary"}


WORDS = [W(f"m{i}", i * 0.5, i * 0.5 + 0.45) for i in range(12)]  # 6 s de parole


def test_durees_proportionnelles_aux_mots():
    durs = compute_scene_durations(["a b c d e f", "g h i j k l"], WORDS, audio_duration=6.4)
    assert durs == [3.0, 3.4]
    assert sum(durs) == pytest.approx(6.4)


def test_durees_scene_unique_et_erreurs():
    assert compute_scene_durations(["a b"], WORDS, 6.4) == [6.4]
    with pytest.raises(VideoEditError):
        compute_scene_durations([], WORDS)
    with pytest.raises(VideoEditError):
        compute_scene_durations(["a"], [])


def test_ffmpeg_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    f = tmp_path / "x"
    f.write_text("x")
    with pytest.raises(VideoEditError, match="FFmpeg introuvable"):
        assemble_video([f], [1.0], f, None, tmp_path / "o.mp4")


def test_echec_ffmpeg_nettoie_les_temporaires(tmp_path):
    f = tmp_path / "x"
    f.write_text("x")
    runner = lambda *a, **k: SimpleNamespace(returncode=1, stderr="boom", stdout="")
    out = tmp_path / "out" / "o.mp4"
    with pytest.raises(VideoEditError, match="boom"):
        assemble_video([f], [1.0], f, None, out, ffmpeg="ffmpeg", runner=runner)
    assert not list(out.parent.glob(".tmp_*")) and not out.exists()


def test_fichier_manquant(tmp_path):
    with pytest.raises(VideoEditError, match="introuvable"):
        assemble_video([tmp_path / "nope.mp4"], [1.0], tmp_path / "a.wav", None, tmp_path / "o.mp4", ffmpeg="ffmpeg")


# --- test réel avec FFmpeg (ignoré s'il n'est pas installé) ---------------------------------

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")


def _synthetic_assets(tmp_path):
    clips = []
    for i, size in enumerate(["1280x720", "720x1280"], 1):
        clip = tmp_path / f"c{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"testsrc=size={size}:rate=25:duration=1", "-pix_fmt", "yuv420p", str(clip)], check=True)
        clips.append(clip)
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=6.4", str(audio)], check=True)
    return clips, audio


@needs_ffmpeg
@pytest.mark.parametrize("framing", ["crop", "blur"])
def test_montage_reel(tmp_path, framing):
    clips, audio = _synthetic_assets(tmp_path)
    wp = tmp_path / "project_1.words.json"
    wp.write_text(json.dumps(WORDS), encoding="utf-8")
    ass = generate_subtitles(wp, {"style": {"subtitles": "modernes"}})["ass_path"]
    durs = compute_scene_durations(["a b c d e f", "g h i j k l"], WORDS, 6.4)
    out = assemble_video(clips, durs, audio, ass, tmp_path / "out" / "v.mp4", framing=framing)
    assert out.exists() and not list(out.parent.glob(".tmp_*"))
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(out)],
                          capture_output=True, text=True).stdout.strip()
    assert info == "1080,1920"
    assert probe_duration(out) == pytest.approx(6.4, abs=0.3)  # les clips de 1 s ont été bouclés


@needs_ffmpeg
def test_pipeline_complet(tmp_path):
    clips, audio = _synthetic_assets(tmp_path)
    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    ch = db.list_channels(dbp)[0]
    pid = db.create_project(ch["id"], "Mon Short !", "sujet", db_path=dbp)
    assert "voix off" in missing_steps(pid, dbp)

    wp = tmp_path / "project_1.words.json"
    wp.write_text(json.dumps(WORDS), encoding="utf-8")
    subs = generate_subtitles(wp, {})
    plan = tmp_path / "scenes.json"
    plan.write_text(json.dumps([
        {"scene": 1, "text": "a b c d e f", "file": str(clips[0]), "credit": "Vidéo : A sur Pixabay — u"},
        {"scene": 2, "text": "g h i j k l", "file": str(clips[1]), "credit": "Vidéo : B sur Pixabay — v"},
    ]), encoding="utf-8")
    db.replace_asset(pid, "audio", audio, "t", db_path=dbp)
    db.replace_asset(pid, "timings", wp, "t", db_path=dbp)
    db.replace_asset(pid, "scenes", plan, "t", db_path=dbp)
    db.replace_asset(pid, "subtitles_ass", subs["ass_path"], "t", db_path=dbp)
    assert missing_steps(pid, dbp) == []

    res = render_project(pid, db_path=dbp, output_dir=tmp_path / "output")
    assert res["path"].name == "mon_short_1.mp4" and res["path"].parent.name == ch["slug"]
    assert db.get_project(pid, dbp)["status"] == "COMPLETED"
    assert len(db.list_exports(pid, dbp)) == 1
    assert "A sur Pixabay" in res["credits"]

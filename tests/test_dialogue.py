import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from core import dialogue
from core.dialogue import (
    DialogueError, dialogue_scene_durations, group_segments, parse_dialogue, speaker_at, to_script_text,
)
from core.script_generator import ScriptGenerationError
from core.subtitle_generator import to_ass, words_to_cues
from core.voice_generator import VoiceGenerationError, generate_dialogue_voice

NAMES = ["Max", "Léa"]


def test_lecture_du_script():
    text = "Max : Salut ! (il rit)\n**Léa** : Salut Max.\nElle continue sur une 2e ligne.\nmax: Et alors ?"
    assert parse_dialogue(text, NAMES) == [(0, "Salut !"), (1, "Salut Max. Elle continue sur une 2e ligne."), (0, "Et alors ?")]


def test_erreurs_du_script():
    with pytest.raises(DialogueError, match="commencer par le nom"):
        parse_dialogue("Bonjour tout le monde", NAMES)
    with pytest.raises(DialogueError, match="inconnu"):
        parse_dialogue("Paul : Salut\nLéa : Salut", NAMES)
    with pytest.raises(DialogueError, match="au moins une réplique de chacun"):
        parse_dialogue("Max : Salut\nMax : Encore moi", NAMES)


def test_groupes_de_repliques():
    segs = [{"text": " ".join(["mot"] * n), "speaker": i % 2} for i, n in enumerate([6, 7, 5, 9, 4, 8, 6, 7, 5, 9])]
    scenes = group_segments(segs, max_scenes=4, min_words=8)
    assert 2 <= len(scenes) <= 4
    assert scenes[0]["segments"][0] == 0 and scenes[-1]["segments"][1] == len(segs) - 1
    assert all(b["segments"][0] == a["segments"][1] + 1 for a, b in zip(scenes, scenes[1:]))   # contiguës, sans trou
    assert sum(len(s["text"].split()) for s in scenes) == sum(len(s["text"].split()) for s in segs)


def test_durees_calees_sur_les_repliques():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 2.2, "end": 4.0}, {"start": 4.2, "end": 6.0}]
    plan = [{"segments": [0, 1]}, {"segments": [2, 2]}]
    assert dialogue_scene_durations(plan, segs, 6.4) == [4.2, 2.2]
    assert sum(dialogue_scene_durations(plan, segs)) == pytest.approx(6.0 + dialogue.TAIL_SECONDS)


def test_qui_parle():
    tl = [{"speaker": 0, "start": 0.0, "end": 1.0}, {"speaker": 1, "start": 1.2, "end": 2.0}]
    assert [speaker_at(tl, t) for t in (0.5, 1.1, 1.5, 2.5)] == [0, None, 1, None]


class FakeGroq:
    def __init__(self, content):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content = content

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))])


def test_ecriture_du_dialogue_avec_groq():
    from core.config import load_channel
    speakers = [{"name": "Max", "role": "le curieux"}, {"name": "Léa", "role": "l'experte"}]
    client = FakeGroq("Max : Tu savais ça ?\nLéa : Pas du tout !\n")
    script = dialogue.generate_dialogue_script("les agents IA", load_channel("tech_ia"), speakers, client=client,
                                               tone="funny")
    assert script == "Max : Tu savais ça ?\nLéa : Pas du tout !"
    prompt = client.calls[0]["messages"][1]["content"]
    assert "Max : le curieux" in prompt and "Nom : texte" in prompt and "humoristique" in prompt and "112 mots" in prompt
    with pytest.raises(ScriptGenerationError, match="mal formé"):
        dialogue.generate_dialogue_script("x", load_channel("tech_ia"), speakers, client=FakeGroq("du texte sans noms"))


def test_sous_titres_par_personnage():
    words = [{"text": "Salut", "start": 0.0, "end": 0.4, "speaker": 0}, {"text": "toi", "start": 0.4, "end": 0.7, "speaker": 0},
             {"text": "Coucou", "start": 0.75, "end": 1.2, "speaker": 1}, {"text": "Max", "start": 1.2, "end": 1.5, "speaker": 1}]
    cues = words_to_cues(words)
    assert [(c["text"], c["speaker"]) for c in cues] == [("Salut toi", 0), ("Coucou Max", 1)]   # jamais mélangés
    ass = to_ass(cues, "modernes")
    assert ass.count("&H00F5C77A&") == 1 and "Salut toi" in ass


# --- Voix du dialogue (FFmpeg réel, service Edge TTS simulé) ---------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")


@pytest.fixture
def tone_mp3(tmp_path):
    path = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.0",
                    str(path)], check=True)
    return path.read_bytes()


def make_fake(tone, record):
    class FakeCommunicate:
        def __init__(self, text, voice, rate="+0%", boundary=None):
            record.append((text, voice, rate))

        async def stream(self):
            yield {"type": "audio", "data": tone}
            yield {"type": "WordBoundary", "offset": 0, "duration": 4_000_000, "text": "un"}
            yield {"type": "WordBoundary", "offset": 5_000_000, "duration": 4_000_000, "text": "deux"}
    return FakeCommunicate


@needs_ffmpeg
def test_voix_du_dialogue(tmp_path, tone_mp3):
    record = []
    speakers = [{"name": "Max", "voice": "fr-FR-HenriNeural"}, {"name": "Léa", "voice": "fr-FR-DeniseNeural"}]
    lines = [(0, "Salut toi"), (1, "Coucou Max"), (0, "Ça va ?")]
    res = generate_dialogue_voice(lines, speakers, 3, rate="+10%", audio_dir=tmp_path, gap=0.2,
                                  communicate_cls=make_fake(tone_mp3, record))
    assert [r[1] for r in record] == ["fr-FR-HenriNeural", "fr-FR-DeniseNeural", "fr-FR-HenriNeural"]   # une voix par personnage
    assert all(r[2] == "+10%" for r in record)
    segs = res["segments"]
    assert [s["speaker"] for s in segs] == [0, 1, 0]
    assert segs[0]["start"] == 0.0 and segs[1]["start"] == pytest.approx(segs[0]["end"] + 0.2, abs=0.01)
    assert all(b["start"] >= a["end"] for a, b in zip(segs, segs[1:]))                                  # pas de chevauchement
    words = json.loads(res["words_path"].read_text(encoding="utf-8"))
    assert [w["speaker"] for w in words] == [0, 0, 1, 1, 0, 0]
    assert words[2]["start"] >= segs[1]["start"] and words[-1]["end"] <= segs[2]["end"] + 0.01
    from core.video_editor import probe_duration
    assert probe_duration(res["audio_path"]) == pytest.approx(segs[-1]["end"], abs=0.2)
    assert not list(tmp_path.glob("*_seg*.mp3"))                                                         # temporaires supprimés


@needs_ffmpeg
def test_voix_dialogue_erreurs(tmp_path, tone_mp3):
    with pytest.raises(VoiceGenerationError):
        generate_dialogue_voice([], [], 1, audio_dir=tmp_path)

    class Broken:
        def __init__(self, *a, **k): pass
        async def stream(self):
            raise RuntimeError("réseau coupé")
            yield
    with pytest.raises(VoiceGenerationError, match="réplique 1"):
        generate_dialogue_voice([(0, "a b"), (1, "c d")], [{"voice": "v"}, {"voice": "w"}], 1, audio_dir=tmp_path,
                                communicate_cls=Broken)
    assert not list(tmp_path.glob("project_*"))  # rien ne reste en cas d'échec


# --- Animation à deux personnages ----------------------------------------------------------------------------

from PIL import Image

from core import animator
from core.animator import SceneSpec, render_scene


@needs_ffmpeg
def test_seul_celui_qui_parle_ouvre_la_bouche(tmp_path, monkeypatch):
    calls = []
    real = animator.draw_head_layer
    monkeypatch.setattr(animator, "draw_head_layer", lambda design, emotion, mouth=0, *a, **kw: (calls.append((design.skin, mouth)),
                                                                                              real(design, emotion, mouth, *a, **kw))[1])
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1080, 1920), (90, 170, 230)).save(bg)
    chars = [{"design": {"skin": "#aaaaaa"}, "emotion": "happy"}, {"design": {"skin": "#bbbbbb"}, "emotion": "sad"}]
    # 1 s de scène : le personnage 0 parle pendant toute la scène, le personnage 1 écoute
    spec = SceneSpec(str(bg), 1.0, 0.0, 0, characters=chars, timeline=[{"speaker": 0, "start": 0.0, "end": 5.0}])
    render_scene(spec, [3] * 40, [2] * 40, tmp_path / "s.mp4")
    mouths_0 = {m for skin, m in calls if skin == "#aaaaaa"}
    mouths_1 = {m for skin, m in calls if skin == "#bbbbbb"}
    assert 3 in mouths_0 and mouths_1 == {0}


@needs_ffmpeg
def test_rendu_dialogue_et_changement_de_locuteur(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1080, 1920), (90, 170, 230)).save(bg)
    chars = [{"design": {"body": "stick", "skin": "#ffffff", "hat": "none"}, "emotion": "happy"},
             {"design": {"body": "cozy", "skin": "#fdf3e3", "hat": "none"}, "emotion": "surprised"}]
    timeline = [{"speaker": 0, "start": 0.0, "end": 0.9}, {"speaker": 1, "start": 1.0, "end": 2.0}]
    out = render_scene(SceneSpec(str(bg), 2.0, 0.0, 1, characters=chars, timeline=timeline), [2] * 70, [1] * 70,
                       tmp_path / "d.mp4")
    info = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,nb_read_frames", "-of", "csv=p=0", str(out)],
                          capture_output=True, text=True).stdout.strip()
    assert info == "1080,1920,60"


# --- Plan visuel du dialogue ----------------------------------------------------------------------------------

from core.scene_planner import plan_dialogue_scenes


def test_plan_du_dialogue():
    speakers = [{"name": "Max"}, {"name": "Léa"}]
    data = [{"visual": "a bedroom at night", "emotions": ["tired", "RELAXED"], "label": "3H", "type": "puppet"},
            {"visual": "a subway", "emotions": ["inconnu"], "label": "", "type": "illustration"}]
    plans, fb = plan_dialogue_scenes([{"text": "a"}, {"text": "b"}], "sommeil", speakers, client=FakeGroq(json.dumps(data)))
    assert not fb and plans[0]["emotions"] == ["tired", "relaxed"] and plans[0]["label"] == "3H"
    assert plans[1]["emotions"] == ["neutral", "neutral"] and plans[1]["type"] == "illustration"   # valeurs inconnues neutralisées
    plans, fb = plan_dialogue_scenes([{"text": "a"}], "sujet", speakers, client=FakeGroq("pas du json"))
    assert fb and plans[0]["emotions"] == ["neutral", "neutral"] and plans[0]["visual"] == "sujet"


def test_derniere_scene_pas_trop_longue():
    segs = [{"text": " ".join(["mot"] * n)} for n in (7, 7, 9, 7, 6, 3)]
    scenes = group_segments(segs)
    assert [s["segments"] for s in scenes] == [[0, 1], [2, 3], [4, 5]]      # 9 mots : scène à part, pas fusionnée
    assert group_segments([{"text": "a b c d e f g h i j"}, {"text": "ok"}])[-1]["segments"] == [0, 1]  # 1 mot : fusionné


# --- Projet en dialogue de bout en bout (FFmpeg réel) -------------------------------------------------------------

@needs_ffmpeg
def test_projet_dialogue_complet(tmp_path, tone_mp3, monkeypatch):
    from core import illustrator
    from core.pipeline import load_segments, missing_steps, render_project
    from core.puppet import PRESETS
    from core.subtitle_generator import generate_subtitles
    from database import db

    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    ch = db.list_channels(dbp)[0]
    a = db.create_character("Max", "puppet_2d", PRESETS["classic_stick"][1].to_json(), db_path=dbp)
    b = db.create_character("Léa", "puppet_2d", PRESETS["cozy_beige"][1].to_json(), db_path=dbp)
    pid = db.create_project(ch["id"], "Dialogue", "sujet", style="puppet_2d", character_id=a, db_path=dbp)
    speakers = [{"name": "Max", "character_id": a, "voice": "fr-FR-HenriNeural", "role": ""},
                {"name": "Léa", "character_id": b, "voice": "fr-FR-DeniseNeural", "role": ""}]
    monkeypatch.setattr(dialogue, "CONFIG_DIR", tmp_path / "cfg")
    dialogue.save_config(pid, speakers, db_path=dbp)

    lines = parse_dialogue("Max : un deux trois\nLéa : quatre cinq six\nMax : sept huit neuf\nLéa : dix onze douze", ["Max", "Léa"])
    res = generate_dialogue_voice(lines, speakers, pid, audio_dir=tmp_path, communicate_cls=make_fake(tone_mp3, []))
    db.replace_asset(pid, "audio", res["audio_path"], "t", db_path=dbp)
    db.replace_asset(pid, "timings", res["words_path"], "t", db_path=dbp)
    ass = generate_subtitles(res["words_path"], {})["ass_path"]
    db.replace_asset(pid, "subtitles_ass", ass, "t", db_path=dbp)
    # sans les répliques horodatées, le montage est refusé avec un message clair
    assert any("dialogue" in m for m in missing_steps(pid, dbp))
    db.replace_asset(pid, "segments", res["segments_path"], "t", db_path=dbp)
    assert load_segments(pid, dbp) == res["segments"]

    scenes = group_segments(res["segments"], min_words=2)
    entries = []
    for i, sc in enumerate(scenes):
        img = illustrator.generate_scene_image(pid, i, "a room", "puppet_2d", out_dir=tmp_path / "img", generator=lambda p, **k: _jpeg())
        anim = {"type": "dialogue", "characters": [{"design": json.loads(db.get_character(c, dbp)["description"]), "emotion": e}
                                                    for c, e in ((a, "happy"), (b, "surprised"))]}
        entries.append(illustrator.build_entry(i, sc["text"], {"visual": "a room", "emotion": "happy", "label": "TOP" if i == 0 else ""},
                                               img, None, animation=anim, segments=sc["segments"]))
    db.replace_asset(pid, "scenes", illustrator.save_plan(entries, tmp_path / "scenes.json"), "t", db_path=dbp)
    assert missing_steps(pid, dbp) == []

    out = render_project(pid, db_path=dbp, output_dir=tmp_path / "out")
    from core.video_editor import probe_duration
    assert out["path"].exists() and db.get_project(pid, dbp)["status"] == "COMPLETED"
    assert probe_duration(out["path"]) == pytest.approx(res["segments"][-1]["end"], abs=0.6)


def _jpeg():
    import io
    from PIL import Image as _Image
    buf = io.BytesIO()
    _Image.new("RGB", (1024, 1024), (120, 180, 230)).save(buf, "JPEG")
    return buf.getvalue()

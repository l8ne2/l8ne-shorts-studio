import base64
import io
import json
import shutil
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from core import character_studio, illustrator
from core.image_generator import ImageGenerationError, generate_image, stable_seed, to_vertical
from core.pipeline import render_project
from core.scene_planner import plan_scenes
from core.styles import get_style, uses_ai_images
from database import db


def jpeg_bytes(color=(80, 160, 220), size=(1024, 1024)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def fake_generator(prompt, seed=None, **kw):
    fake_generator.calls.append((prompt, seed))
    return jpeg_bytes()


fake_generator.calls = []


# --- Cloudflare --------------------------------------------------------------------------------

class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data


def session_returning(*responses):
    it = iter(responses)
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r

    return SimpleNamespace(post=post, calls=calls)


def test_generation_ok():
    ok = Resp(200, {"result": {"image": base64.b64encode(b"IMG").decode()}, "success": True})
    s = session_returning(ok)
    assert generate_image("a cat", seed=5, account_id="acc", token="tok", session=s) == b"IMG"
    assert s.calls[0]["json"] == {"prompt": "a cat", "steps": 4}  # pas de "seed" : refusé par Cloudflare (400)
    assert s.calls[0]["headers"]["Authorization"] == "Bearer tok" and "/acc/ai/run/" in s.calls[0]["url"]


@pytest.mark.parametrize("status", [401, 403, 429, 400])
def test_erreurs_cloudflare_sans_nouvel_essai(status):
    s = session_returning(Resp(status, text="x"), Resp(200))
    with pytest.raises(ImageGenerationError):
        generate_image("a", account_id="a", token="t", session=s, sleep=lambda x: None)
    assert len(s.calls) == 1


def test_nouvel_essai_sur_erreur_serveur():
    ok = Resp(200, {"result": {"image": base64.b64encode(b"X").decode()}})
    s = session_returning(Resp(503), RuntimeError("timeout"), ok)
    assert generate_image("a", account_id="a", token="t", session=s, sleep=lambda x: None) == b"X"
    assert len(s.calls) == 3


def test_cles_absentes(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(ImageGenerationError, match="CLOUDFLARE"):
        generate_image("a")


def test_graine_stable_et_recadrage(tmp_path):
    assert stable_seed("a", 1) == stable_seed("a", 1) != stable_seed("a", 2)
    src = tmp_path / "s.jpg"
    src.write_bytes(jpeg_bytes())
    out = to_vertical(src, tmp_path / "v.jpg")
    assert Image.open(out).size == (1080, 1920)


# --- Styles, prompts, personnages --------------------------------------------------------------

def test_styles():
    assert not uses_ai_images("stock") and uses_ai_images("game_3d")
    assert get_style("inconnu")["composition"] == "stock"
    assert get_style("cutaway_3d")["labels"] and not get_style("cutaway_3d")["characters"]


def test_candidats_et_sprite(tmp_path):
    fake_generator.calls.clear()
    res = character_studio.generate_candidates(1, "game_3d", "a red robot", tmp_path, emotions=["happy", "sad"],
                                               generator=fake_generator)
    assert len(res["happy"]) == 2 and all(p.exists() for p in res["sad"])
    assert "a red robot" in fake_generator.calls[0][0] and "grey background" in fake_generator.calls[0][0]
    assert len({seed for _, seed in fake_generator.calls}) == 4  # variantes différentes

    img = Image.new("RGB", (512, 512), (200, 200, 200))
    ImageDraw.Draw(img).ellipse((150, 100, 350, 400), fill=(220, 50, 40))
    src = tmp_path / "c.jpg"
    img.save(src)
    sprite = Image.open(character_studio.make_sprite(src, tmp_path / "s.png", method="simple"))
    assert sprite.mode == "RGBA" and sprite.getpixel((0, 0))[3] == 0
    assert sprite.getpixel((sprite.width // 2, sprite.height // 2))[3] == 255


def test_sprite_sans_personnage(tmp_path):
    src = tmp_path / "plain.jpg"
    src.write_bytes(jpeg_bytes((200, 200, 200)))
    with pytest.raises(character_studio.CutoutError):
        character_studio.make_sprite(src, tmp_path / "x.png", method="simple")


# --- Plan de scènes ----------------------------------------------------------------------------

class FakeGroq:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))])))


def test_plan_scenes_valide_et_nettoie():
    data = [{"visual": "a pool", "emotion": "HAPPY", "label": "Filtre"},
            {"visual": "soil layers", "emotion": "bizarre", "label": "un deux trois quatre"}]
    plans, fb = plan_scenes(["a", "b"], "piscine", "cutaway_3d", client=FakeGroq(json.dumps(data)))
    assert not fb and plans[0]["emotion"] == "happy" and plans[0]["label"] == "Filtre"
    assert plans[1]["emotion"] == "neutral" and plans[1]["label"] == ""  # émotion inconnue / étiquette trop longue


def test_plan_scenes_repli():
    plans, fb = plan_scenes(["a", "b"], "sujet", "game_3d", client=FakeGroq("pas du json"))
    assert fb and [p["visual"] for p in plans] == ["sujet", "sujet"]


# --- Illustrations -----------------------------------------------------------------------------

def test_prompts_selon_composition():
    sprite = illustrator.build_scene_prompt("game_3d", "a park", "a robot")
    assert "nobody in the scene" in sprite and "a robot" not in sprite
    full = illustrator.build_scene_prompt("cartoon_2d", "a park", "a robot")
    assert "a robot" in full


def test_pick_sprite(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    ex = {"neutral": str(a), "happy": str(b), "sad": str(tmp_path / "absent.png")}
    assert illustrator.pick_sprite(ex, "happy") == str(b)
    assert illustrator.pick_sprite(ex, "sad") == str(a)  # absent -> neutre
    assert illustrator.pick_sprite({}, "happy") is None


def test_generation_scene(tmp_path):
    path = illustrator.generate_scene_image(7, 0, "a pool", "cutaway_3d", out_dir=tmp_path, generator=fake_generator)
    assert path.name == "scene_1.jpg" and Image.open(path).size == (1080, 1920)


# --- Migration de base existante ---------------------------------------------------------------

def test_migration_ancienne_base(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE channels (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL, niche TEXT, config TEXT);
        CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL, title TEXT NOT NULL,
        topic TEXT, script TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'DRAFT', error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO channels (slug, name) VALUES ('x', 'X');
        INSERT INTO projects (channel_id, title, created_at, updated_at) VALUES (1, 'Ancien', 'a', 'a');""")
    conn.commit()
    conn.close()
    db.init_db(path)
    p = db.list_projects(db_path=path)[0]
    assert p["title"] == "Ancien" and p["style"] == "stock" and p["character_id"] is None


def test_personnages_en_base(tmp_path):
    path = tmp_path / "t.db"
    db.init_db(path)
    cid = db.create_character("Robo", "game_3d", "a robot", db_path=path)
    db.set_expression(cid, "happy", "h1.png", db_path=path)
    db.set_expression(cid, "happy", "h2.png", db_path=path)  # remplace
    assert db.list_expressions(cid, path) == {"happy": "h2.png"}
    assert [c["name"] for c in db.list_characters("game_3d", path)] == ["Robo"]
    assert db.list_characters("cartoon_2d", path) == []


# --- Montage complet d'un projet illustré (FFmpeg réel) -------------------------------------------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")
def test_pipeline_projet_illustre(tmp_path):
    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    ch = db.list_channels(dbp)[0]
    pid = db.create_project(ch["id"], "Piscine", "sujet", style="cutaway_3d", db_path=dbp)

    words = [{"text": f"m{i}", "start": i * .5, "end": i * .5 + .45, "kind": "WordBoundary"} for i in range(8)]
    wp = tmp_path / "project_1.words.json"
    wp.write_text(json.dumps(words))
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=4.4", str(audio)], check=True)
    ass = tmp_path / "project_1.ass"
    ass.write_text("[Script Info]\nPlayResX: 1080\nPlayResY: 1920\n", encoding="utf-8")

    entries = []
    for i in range(2):
        img = illustrator.generate_scene_image(pid, i, "a pool", "cutaway_3d", out_dir=tmp_path / "img", generator=fake_generator)
        entries.append(illustrator.build_entry(i, "a b c d" if i == 0 else "e f g h",
                                               {"visual": "a pool", "emotion": "neutral", "label": "Filtre" if i == 0 else ""},
                                               img, None))
    plan = illustrator.save_plan(entries, tmp_path / "scenes.json")
    for typ, path in (("audio", audio), ("timings", wp), ("scenes", plan), ("subtitles_ass", ass)):
        db.replace_asset(pid, typ, path, "t", db_path=dbp)

    res = render_project(pid, db_path=dbp, output_dir=tmp_path / "output")
    assert res["path"].exists() and db.get_project(pid, dbp)["status"] == "COMPLETED"
    assert (tmp_path / "project_1_final.ass").exists()  # .ass régénéré (étiquettes + style du look)
    assert "FLUX" in res["credits"]


# --- Marionnette animée -------------------------------------------------------------------------

from core import puppet
from core.animator import SceneSpec, camera_box, render_scene
from core.lipsync import audio_envelope, gesture_levels, mouth_levels


def test_marionnette_dessin_et_json():
    d = puppet.PuppetDesign(hat="helmet", outfit="#ff0000")
    assert puppet.PuppetDesign.from_json(d.to_json()) == d
    assert puppet.PuppetDesign.from_json("pas du json").hat == "cap"          # valeurs par défaut
    assert puppet.PuppetDesign.from_json('{"hat": "inconnu"}').hat == "none"  # chapeau inconnu neutralisé
    a = puppet.draw_puppet(d, "neutral", display_height=300)
    assert a.mode == "RGBA" and a.height == 300 and a.getbbox()
    different = [puppet.draw_puppet(d, e, display_height=300).tobytes() for e in ("neutral", "angry", "happy")]
    assert len(set(different)) == 3                                           # expressions distinctes
    assert puppet.draw_puppet(d, "neutral", mouth=3, display_height=300).tobytes() != a.tobytes()
    assert puppet.draw_puppet(d, "neutral", blink=True, display_height=300).tobytes() != a.tobytes()


def test_camera():
    x0, y0, x1, y1 = camera_box(0, 0.0, 3.0, "neutral")
    assert (x1 - x0, y1 - y0) == pytest.approx((1080, 1920))                  # zoom 1.0 au début
    x0, y0, x1, y1 = camera_box(0, 3.0, 3.0, "neutral")
    assert x1 - x0 == pytest.approx(1080 / 1.12)
    for t in (0.0, 0.1, 1.0):
        x0, y0, x1, y1 = camera_box(1, t, 3.0, "angry")                       # reste dans l'image
        assert 0 <= x0 and x1 <= 1080 + 1e-6 and 0 <= y0 and y1 <= 1920 + 1e-6


needs_ffmpeg_anim = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")


@needs_ffmpeg_anim
def test_synchro_labiale(tmp_path):
    wav = tmp_path / "v.wav"
    # 1 s de silence, 1 s de bruit fort, 1 s de silence
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anoisesrc=d=1:c=pink:a=0.6", "-f", "lavfi", "-i", "anullsrc=d=1", "-filter_complex",
                    "[1:a][0:a][1:a]concat=n=3:v=0:a=1", str(wav)], check=True)
    env = audio_envelope(wav)
    levels = mouth_levels(env)
    assert len(levels) == len(env) == pytest.approx(90, abs=2)
    assert set(levels[:20]) == {0} and set(levels[-20:]) == {0}               # silence : bouche fermée
    assert max(levels[35:55]) >= 2                                            # voix : bouche ouverte
    assert max(gesture_levels(env)) >= 1


@needs_ffmpeg_anim
def test_rendu_scene_animee(tmp_path):
    bg = tmp_path / "bg.jpg"
    Image.new("RGB", (1080, 1920), (90, 170, 230)).save(bg)
    spec = SceneSpec(str(bg), 1.0, 0.0, 0, "happy", design={"hat": "cap"})
    out = render_scene(spec, [0, 1, 2, 3] * 10, [0, 1, 2] * 14, tmp_path / "s.mp4")
    info = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,nb_read_frames", "-of", "csv=p=0", str(out)],
                          capture_output=True, text=True).stdout.strip()
    assert info == "1080,1920,30"
    frames = []
    for t in (0.05, 0.6):                                                     # le personnage bouge entre 2 images
        png = tmp_path / f"f{t}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1",
                        str(png)], check=True)
        frames.append(Image.open(png).tobytes())
    assert frames[0] != frames[1]


@needs_ffmpeg_anim
def test_pipeline_marionnette(tmp_path):
    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    ch = db.list_channels(dbp)[0]
    cid = db.create_character("Bob", "puppet_2d", puppet.PuppetDesign().to_json(), db_path=dbp)
    pid = db.create_project(ch["id"], "Parle", "sujet", style="puppet_2d", character_id=cid, db_path=dbp)
    words = [{"text": f"m{i}", "start": i * .5, "end": i * .5 + .45, "kind": "WordBoundary"} for i in range(8)]
    wp = tmp_path / "project_1.words.json"
    wp.write_text(json.dumps(words))
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=4.4:c=pink:a=0.5",
                    str(audio)], check=True)
    from core.subtitle_generator import to_ass, words_to_cues
    ass = tmp_path / "project_1.ass"
    ass.write_text(to_ass(words_to_cues(words), "modernes"), encoding="utf-8")
    entries = []
    for i in range(2):
        img = illustrator.generate_scene_image(pid, i, "a village", "puppet_2d", out_dir=tmp_path / "img",
                                               generator=fake_generator)
        entries.append(illustrator.build_entry(
            i, "a b c d" if i == 0 else "e f g h", {"visual": "v", "emotion": "angry" if i else "happy", "label": ""},
            img, None, animation={"type": "puppet", "design": json.loads(db.get_character(cid, dbp)["description"])}))
    plan = illustrator.save_plan(entries, tmp_path / "scenes.json")
    for typ, path in (("audio", audio), ("timings", wp), ("scenes", plan), ("subtitles_ass", ass)):
        db.replace_asset(pid, typ, path, "t", db_path=dbp)
    res = render_project(pid, db_path=dbp, output_dir=tmp_path / "output")
    assert res["path"].exists() and db.get_project(pid, dbp)["status"] == "COMPLETED"
    assert not list((tmp_path / "output").rglob(".anim_*"))                   # fichiers temporaires supprimés


# --- Accroche, aperçu, kit de publication --------------------------------------------------------------

def test_prompt_accroche():
    from core.config import load_channel
    from core.script_generator import build_messages
    user = build_messages("IA", load_channel("tech_ia"))[1]["content"]
    assert "ACCROCHE" in user and "salutation" in user and "métaphore" in user and "CHUTE" in user


def test_decoupe_apercu():
    from core.pipeline import trim_scenes
    plan = [{"n": 1}, {"n": 2}, {"n": 3}]
    kept, durs = trim_scenes(plan, [8.0, 8.0, 8.0], 20)
    assert [k["n"] for k in kept] == [1, 2, 3] and durs == [8.0, 8.0, 4.0]    # dernière scène raccourcie
    kept, durs = trim_scenes(plan, [8.0, 8.0, 8.0], 8)
    assert len(kept) == 1 and durs == [8.0]                                  # inutile d'en rendre plus


def test_kit_groq_et_credits():
    from core.config import load_channel
    from core.publishing_kit import AI_NOTICE, build_kit, checklist, kit_to_text
    data = {"titles": [f"Titre {i}" for i in range(7)], "description": "Résumé. #Shorts",
            "tags": ["#ia", "agents"], "pinned_comment": "Et toi ?"}
    kit, fb = build_kit("agents", "script", load_channel("tech_ia"), "Vidéo : Bob sur Pixabay", "game_3d",
                        client=FakeGroq("```json\n" + json.dumps(data) + "\n```"))
    assert not fb and len(kit["titles"]) == 5 and kit["tags"] == ["ia", "agents"]
    assert "Bob sur Pixabay" in kit["description"] and AI_NOTICE in kit["description"]
    items = checklist({"status": "COMPLETED"}, 22.4, "x", "stock")
    assert items[0][1] and items[1][1] and any(ok is None for _, ok in items)   # vérifications manuelles à faire
    text = kit_to_text(kit, items)
    assert "TITRES PROPOSÉS" in text and "[ ]" in text and "[x]" in text


def test_kit_repli():
    from core.config import load_channel
    from core.publishing_kit import build_kit
    kit, fb = build_kit("agents IA", "script", load_channel("tech_ia"), client=FakeGroq("pas du json"))
    assert fb and kit["titles"] == ["agents IA"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")
def test_apercu_ne_touche_pas_au_projet(tmp_path):
    from core.pipeline import render_project
    from core.subtitle_generator import to_ass, words_to_cues
    dbp = tmp_path / "t.db"
    db.init_db(dbp)
    ch = db.list_channels(dbp)[0]
    pid = db.create_project(ch["id"], "Apercu", "sujet", style="cutaway_3d", db_path=dbp)
    db.update_script(pid, "x", dbp)
    words = [{"text": f"m{i}", "start": i * .5, "end": i * .5 + .45, "kind": "WordBoundary"} for i in range(16)]
    wp = tmp_path / "project_1.words.json"
    wp.write_text(json.dumps(words))
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=8.4", str(audio)], check=True)
    ass = tmp_path / "p.ass"
    ass.write_text(to_ass(words_to_cues(words), "modernes"), encoding="utf-8")
    entries = []
    for i in range(2):
        img = illustrator.generate_scene_image(pid, i, "a", "cutaway_3d", out_dir=tmp_path / "img", generator=fake_generator)
        entries.append(illustrator.build_entry(i, " ".join(f"w{k}" for k in range(8)), {"visual": "a", "emotion": "neutral", "label": ""}, img, None))
    plan = illustrator.save_plan(entries, tmp_path / "scenes.json")
    for typ, path in (("audio", audio), ("timings", wp), ("scenes", plan), ("subtitles_ass", ass)):
        db.replace_asset(pid, typ, path, "t", db_path=dbp)
    res = render_project(pid, db_path=dbp, output_dir=tmp_path / "out", preview_seconds=3)
    assert res["preview"] and res["path"].name.endswith("_apercu.mp4")
    from core.video_editor import probe_duration
    assert probe_duration(res["path"]) == pytest.approx(3.0, abs=0.3)
    assert db.get_project(pid, dbp)["status"] == "DRAFT" and db.list_exports(pid, dbp) == []


# --- Ambiances, ton, scènes illustrées complètes ------------------------------------------------------

def test_resolution_du_look():
    from core.looks import LOOKS, resolve_look
    assert resolve_look("auto", {"look": "thriller_sombre"}) is LOOKS["thriller_sombre"]   # selon la chaîne
    assert resolve_look("nuit_cosy", {"look": "thriller_sombre"}) is LOOKS["nuit_cosy"]    # choix du projet
    assert resolve_look(None, {})["grade"] == "" and resolve_look("inconnu", {})["bg_prefix"] == ""


def test_chaines_ont_un_look():
    from core.config import load_all_channels
    from core.looks import LOOKS
    for slug, cfg in load_all_channels().items():
        assert cfg["look"] in LOOKS, slug


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")
@pytest.mark.parametrize("look", ["pop_clair", "thriller_sombre", "nuit_cosy", "chaud_colore"])
def test_etalonnage_valide_dans_ffmpeg(tmp_path, look):
    """Chaque étalonnage doit être accepté par FFmpeg (un filtre mal écrit ferait échouer tout le montage)."""
    from core.looks import LOOKS
    from core.video_editor import assemble_video
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=1",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio)], check=True)
    out = assemble_video([clip], [1.0], audio, None, tmp_path / "o.mp4", grade=LOOKS[look]["grade"])
    assert out.exists() and out.stat().st_size > 1000


def test_ton_du_script():
    from core.config import load_channel
    from core.script_generator import TONES, build_messages
    cfg = load_channel("tech_ia")
    assert "humoristique" in build_messages("IA", cfg, "funny")[1]["content"]
    assert build_messages("IA", cfg, "channel")[1]["content"] == build_messages("IA", cfg)[1]["content"]
    assert set(TONES) >= {"channel", "funny", "suspense"}


def test_description_du_personnage_pour_l_ia():
    d = puppet.PuppetDesign(skin="#f5cf9d", outfit="#c0392b", hat="beanie", hat_color="#f1c40f")
    text = puppet.describe_design(d)
    assert "stickman" in text and "peach" in text and "yellow beanie" in text and "red shirt" in text
    assert "no hat" in puppet.describe_design(puppet.PuppetDesign(hat="none"))


def test_prompt_scene_complete_vs_decor_vide():
    empty = illustrator.build_scene_prompt("puppet_2d", "a bedroom", "a stickman", "cozy look")
    assert "nobody in the scene" in empty and "a stickman" not in empty and "cozy look" in empty
    full = illustrator.build_scene_prompt("puppet_2d", "a bedroom", "a stickman", full_scene=True)
    assert "a stickman" in full and "nobody in the scene" not in full


def test_plan_avec_type_de_scene():
    data = [{"visual": "a", "emotion": "sad", "label": "3H", "type": "illustration"},
            {"visual": "b", "emotion": "happy", "label": "", "type": "bizarre"}]
    plans, fb = plan_scenes(["x", "y"], "t", "puppet_2d", client=FakeGroq(json.dumps(data)))
    assert [p["type"] for p in plans] == ["illustration", "puppet"]            # type inconnu -> marionnette
    assert all(p["type"] == "puppet" for p in plan_scenes(["x"], "t", "puppet_2d", client=FakeGroq("?"))[0])


def test_look_en_base(tmp_path):
    path = tmp_path / "t.db"
    db.init_db(path)
    ch = db.list_channels(path)[0]
    assert db.get_project(db.create_project(ch["id"], "A", db_path=path), path)["look"] == "auto"
    pid = db.create_project(ch["id"], "B", look="nuit_cosy", db_path=path)
    assert db.get_project(pid, path)["look"] == "nuit_cosy"

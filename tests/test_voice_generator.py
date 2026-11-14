import json

import pytest

from core.config import load_channel
import shutil
import subprocess

from core.voice_generator import (
    VoiceGenerationError, compute_cuts, generate_voice, shift_words, tighten_pauses,
)
from database import db


class FakeCommunicate:
    def __init__(self, text, voice, rate="+0%", boundary=None):
        self.voice, self.rate = voice, rate

    async def stream(self):
        yield {"type": "audio", "data": b"ID3fake"}
        yield {"type": "WordBoundary", "offset": 0, "duration": 5_000_000, "text": "Bonjour"}
        yield {"type": "WordBoundary", "offset": 6_000_000, "duration": 4_000_000, "text": "monde"}
        yield {"type": "audio", "data": b"more"}


class BrokenCommunicate(FakeCommunicate):
    async def stream(self):
        yield {"type": "audio", "data": b"partial"}
        raise RuntimeError("réseau coupé")


class SilentCommunicate(FakeCommunicate):
    async def stream(self):
        yield {"type": "WordBoundary", "offset": 0, "duration": 1, "text": "x"}


def test_generation_ok(tmp_path):
    cfg = load_channel("tech_ia")
    res = generate_voice("Bonjour monde", cfg, 1, audio_dir=tmp_path, communicate_cls=FakeCommunicate)
    assert res["audio_path"].read_bytes() == b"ID3fakemore"
    assert res["voice"] == "fr-FR-HenriNeural"
    assert res["duration"] == pytest.approx(1.0)
    words = json.loads(res["words_path"].read_text(encoding="utf-8"))
    assert [w["text"] for w in words] == ["Bonjour", "monde"]


def test_echec_ne_laisse_pas_de_fichier(tmp_path):
    cfg = load_channel("tech_ia")
    with pytest.raises(VoiceGenerationError):
        generate_voice("Bonjour", cfg, 2, audio_dir=tmp_path, communicate_cls=BrokenCommunicate)
    assert list(tmp_path.iterdir()) == []


def test_audio_vide(tmp_path):
    with pytest.raises(VoiceGenerationError):
        generate_voice("Bonjour", load_channel("tech_ia"), 3, audio_dir=tmp_path, communicate_cls=SilentCommunicate)


def test_texte_vide(tmp_path):
    with pytest.raises(VoiceGenerationError):
        generate_voice("  ", load_channel("tech_ia"), 4, audio_dir=tmp_path, communicate_cls=FakeCommunicate)


def test_asset_remplace(tmp_path):
    path = tmp_path / "t.db"
    db.init_db(path)
    ch = db.list_channels(path)[0]
    pid = db.create_project(ch["id"], "T", db_path=path)
    db.replace_asset(pid, "audio", "a.mp3", "edge-tts", db_path=path)
    db.replace_asset(pid, "audio", "b.mp3", "edge-tts", db_path=path)
    assets = db.list_assets(pid, "audio", db_path=path)
    assert len(assets) == 1 and assets[0]["file_path"] == "b.mp3"


# --- Pauses resserrées ----------------------------------------------------------------------------

def W(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_coupes_calculees():
    words = [W("a", 0.6, 1.0), W("b", 1.1, 1.5), W("c", 2.5, 3.0)]
    cuts = compute_cuts(words, cap=0.2, lead=0.1)
    assert cuts == [(0.0, pytest.approx(0.5)), (pytest.approx(1.6), pytest.approx(2.4))]  # début + pause de 1 s
    assert compute_cuts([W("a", 0.1, 0.5), W("b", 0.6, 1.0)]) == []                      # rien à couper


def test_horodatage_recale():
    words = [W("a", 0.6, 1.0), W("b", 1.1, 1.5), W("c", 2.5, 3.0)]
    out = shift_words(words, compute_cuts(words, cap=0.2, lead=0.1))
    assert out[0]["start"] == pytest.approx(0.1)           # silence initial réduit à 0,1 s
    assert out[2]["start"] - out[1]["end"] == pytest.approx(0.2)  # pause réduite à 0,2 s
    assert out[2]["end"] - out[2]["start"] == pytest.approx(0.5)  # durée d'un mot inchangée


def test_sans_ffmpeg_ou_echec_on_garde_l_original(tmp_path, monkeypatch):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    words = [W("a", 0.0, 0.5), W("b", 3.0, 3.5)]
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert tighten_pauses(audio, words) == (words, False)
    bad = lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "boom"})()
    assert tighten_pauses(audio, words, ffmpeg="ffmpeg", runner=bad) == (words, False)
    assert audio.read_bytes() == b"x"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg non installé")
def test_pauses_resserrees_avec_ffmpeg(tmp_path):
    # 0,6 s de silence, 1 s de son, 1 s de silence, 1 s de son
    audio = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=d=0.6", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1", "-f", "lavfi", "-i", "anullsrc=d=1", "-f", "lavfi",
                    "-i", "sine=frequency=660:duration=1", "-filter_complex", "[0][1][2][3]concat=n=4:v=0:a=1",
                    str(audio)], check=True)
    words = [W("un", 0.6, 1.6), W("deux", 2.6, 3.6)]
    new_words, changed = tighten_pauses(audio, words, cap=0.2)
    assert changed
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=nw=1:nk=1", str(audio)], capture_output=True, text=True).stdout)
    assert dur == pytest.approx(3.6 - 0.5 - 0.8, abs=0.15)   # 3,6 s au départ ; début -0,5 s, pause -0,8 s
    assert new_words[0]["start"] == pytest.approx(0.12) and new_words[1]["start"] - new_words[0]["end"] == pytest.approx(0.2)
    assert not list(tmp_path.glob("*.tight.mp3"))


def test_generation_resserre_les_pauses(tmp_path):
    class Pauses(FakeCommunicate):
        async def stream(self):
            yield {"type": "audio", "data": b"ID3fake"}
            yield {"type": "WordBoundary", "offset": 0, "duration": 5_000_000, "text": "Bonjour"}
            yield {"type": "WordBoundary", "offset": 40_000_000, "duration": 5_000_000, "text": "monde"}
    cfg = {"voice": {"name": "v", "rate": "+0%", "tighten": False}}
    res = generate_voice("Bonjour monde", cfg, 9, audio_dir=tmp_path, communicate_cls=Pauses)
    assert res["duration"] == pytest.approx(4.5)              # réglage « tighten: false » : rien n'est coupé

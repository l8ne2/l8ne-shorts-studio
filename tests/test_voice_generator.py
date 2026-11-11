import json

import pytest

from core.config import load_channel
from core.voice_generator import VoiceGenerationError, generate_voice
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

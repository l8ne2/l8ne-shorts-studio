from types import SimpleNamespace

import pytest

from core.visual_finder import (
    VisualSearchError, build_credits, download_video, plan_queries, search_videos, split_scenes,
)

SCRIPT = ("L'IA change tout. Les agents savent planifier des tâches complexes en autonomie totale. "
          "Ils utilisent des outils comme un navigateur ou un terminal pour agir. "
          "Mais attention aux erreurs, car ils se trompent parfois sans le dire. "
          "Alors, êtes-vous prêt à leur confier vos projets importants ?")


def test_decoupage_en_scenes():
    scenes = split_scenes(SCRIPT, max_scenes=3)
    assert 1 <= len(scenes) <= 3
    assert " ".join(scenes).replace("  ", " ") == SCRIPT
    assert split_scenes("   ") == []


class FakeGroq:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))])))


def test_requetes_groq():
    scenes = ["a b", "c d"]
    queries, fb = plan_queries(scenes, "IA", client=FakeGroq('```json\n["robot hand", "code screen"]\n```'))
    assert queries == ["robot hand", "code screen"] and not fb


def test_requetes_fallback_si_reponse_invalide():
    queries, fb = plan_queries(["a", "b"], "IA", client=FakeGroq("n'importe quoi"))
    assert queries == ["IA", "IA"] and fb


class FakeResp:
    def __init__(self, status=200, data=None, chunks=()):
        self.status_code, self._data, self._chunks = status, data or {}, chunks

    def json(self):
        return self._data

    def iter_content(self, chunk_size=0):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


PEXELS = {"videos": [{
    "id": 1, "url": "https://pexels.com/video/1", "image": "https://img/1.jpg", "duration": 12,
    "user": {"name": "Jane", "url": "https://pexels.com/@jane"},
    "video_files": [
        {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "https://v/uhd.mp4"},
        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://v/hd.mp4"},
        {"file_type": "video/mp4", "width": 540, "height": 960, "link": "https://v/sd.mp4"},
    ]}]}


def test_recherche_choisit_portrait_1080():
    session = SimpleNamespace(get=lambda *a, **k: FakeResp(200, PEXELS))
    c = search_videos("robot", api_key="k", session=session, provider="pexels")
    assert len(c) == 1 and c[0]["link"] == "https://v/hd.mp4" and c[0]["author"] == "Jane"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_erreurs_pexels(status):
    session = SimpleNamespace(get=lambda *a, **k: FakeResp(status))
    with pytest.raises(VisualSearchError):
        search_videos("x", api_key="k", session=session, provider="pexels")


def test_cle_absente(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.delenv("VISUAL_PROVIDER", raising=False)
    with pytest.raises(VisualSearchError):
        search_videos("x")


PIXABAY = {"hits": [
    {"id": 7, "pageURL": "https://pixabay.com/videos/x-7/", "duration": 15, "user": "Bob", "picture_id": "abc",
     "videos": {"large": {"url": "https://p/large.mp4", "width": 1920, "height": 1080},
                "medium": {"url": "https://p/medium.mp4", "width": 1280, "height": 720},
                "small": {"url": "", "width": 0, "height": 0}}},
    {"id": 8, "pageURL": "https://pixabay.com/videos/y-8/", "duration": 9, "user": "Ann", "picture_id": "def",
     "videos": {"medium": {"url": "https://p/v.mp4", "width": 1080, "height": 1920}}},
    {"id": 9, "videos": {"large": {"url": ""}}},
]}


def test_pixabay_choix_fichier_portrait_en_premier():
    session = SimpleNamespace(get=lambda *a, **k: FakeResp(200, PIXABAY))
    c = search_videos("robot", api_key="k", session=session, provider="pixabay")
    assert [x["id"] for x in c] == [8, 7]  # portrait d'abord, hit sans vidéo ignoré
    assert c[1]["link"] == "https://p/large.mp4" and c[1]["author"] == "Bob"
    assert c[1]["preview"].endswith("abc_640x360.jpg")


def test_pixabay_erreurs():
    for status in (400, 429, 500):
        session = SimpleNamespace(get=lambda *a, **k: FakeResp(status))
        with pytest.raises(VisualSearchError):
            search_videos("x", api_key="k", session=session, provider="pixabay")


def test_fournisseur_choisi_selon_la_cle(monkeypatch):
    from core.visual_finder import _resolve_provider
    monkeypatch.delenv("VISUAL_PROVIDER", raising=False)
    monkeypatch.setenv("PIXABAY_API_KEY", "k")
    assert _resolve_provider() == "pixabay"
    monkeypatch.delenv("PIXABAY_API_KEY")
    assert _resolve_provider() == "pexels"


def test_cache_24h(tmp_path, monkeypatch):
    import core.visual_finder as vf
    monkeypatch.setattr(vf, "CACHE_FILE", tmp_path / "c.json")
    vf._cache_set("k", [1])
    assert vf._cache_get("k") == [1]
    assert vf._cache_get("autre") is None


def test_credit_pixabay():
    from core.visual_finder import credit_line
    assert "Pixabay" in credit_line({"provider": "pixabay", "author": "Bob", "page_url": "https://p"})


def test_telechargement_atomique(tmp_path):
    ok = SimpleNamespace(get=lambda *a, **k: FakeResp(200, chunks=[b"ab", b"cd"]))
    path = download_video({"link": "u"}, tmp_path / "s.mp4", session=ok)
    assert path.read_bytes() == b"abcd" and not list(tmp_path.glob("*.part"))
    ko = SimpleNamespace(get=lambda *a, **k: FakeResp(403))
    with pytest.raises(VisualSearchError):
        download_video({"link": "u"}, tmp_path / "t.mp4", session=ko)
    assert not (tmp_path / "t.mp4").exists() and not list(tmp_path.glob("*.part"))


def test_credits_dedoublonnes():
    c = {"author": "Jane", "page_url": "https://p/1"}
    assert build_credits([c, c]).count("Jane") == 1

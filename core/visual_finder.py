"""Recherche et téléchargement de visuels vidéo, Pixabay ou Pexels (Phase 2).

Le script est découpé en scènes ; Groq propose une requête de recherche (en anglais)
par scène ; Pixabay (ou Pexels) renvoie des vidéos parmi lesquelles tu choisis.
"""
import json
import os
import re
import time
from math import ceil
from pathlib import Path

from core.config import ROOT

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
VIDEOS_DIR = ROOT / "media" / "videos"
MAX_WIDTH = 1080


class VisualSearchError(Exception):
    """Erreur lors de la recherche ou du téléchargement de visuels."""


# --- Découpage en scènes -----------------------------------------------------

def split_scenes(script: str, max_scenes: int = 8, min_words: int = 8) -> list:
    """Regroupe les phrases du script en au plus `max_scenes` scènes."""
    sentences = [s for s in re.split(r"(?<=[.!?…])\s+", script.strip()) if s.strip()]
    if not sentences:
        return []
    per_scene = max(min_words, ceil(len(script.split()) / max_scenes))
    scenes, current, count = [], [], 0
    for sentence in sentences:
        current.append(sentence)
        count += len(sentence.split())
        if count >= per_scene:
            scenes.append(" ".join(current))
            current, count = [], 0
    if current:
        if scenes and count < min_words:
            scenes[-1] += " " + " ".join(current)
        else:
            scenes.append(" ".join(current))
    while len(scenes) > max_scenes:
        last = scenes.pop()
        scenes[-1] += " " + last
    return scenes


# --- Requêtes de recherche (Groq) --------------------------------------------

def plan_queries(scenes: list, topic: str, client=None, model: str = None):
    """Retourne (requêtes, fallback_utilisé). Une requête en anglais par scène."""
    fallback = [topic] * len(scenes)
    try:
        if client is None:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                return fallback, True
            from groq import Groq

            client = Groq(api_key=api_key)
        from core.script_generator import call_groq

        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(scenes))
        prompt = (
            f"Sujet de la vidéo : {topic}\n\nScènes :\n{numbered}\n\n"
            f"Pour chaque scène, donne une requête de 2 à 4 mots EN ANGLAIS pour trouver une "
            f"vidéo d'illustration (stock) concrète et visuelle. Réponds uniquement avec un "
            f"tableau JSON de {len(scenes)} chaînes, sans autre texte."
        )
        content = call_groq(client, [{"role": "user", "content": prompt}], max_tokens=1500,
                            temperature=0.3, model=model)
        text = re.sub(r"```(?:json)?", "", content).strip()
        queries = json.loads(text)
        if (
            isinstance(queries, list)
            and len(queries) == len(scenes)
            and all(isinstance(q, str) and q.strip() for q in queries)
        ):
            return [q.strip() for q in queries], False
    except Exception:
        pass
    return fallback, True


# --- Recherche de vidéos (Pixabay ou Pexels) ---------------------------------

PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"
CACHE_FILE = ROOT / "media" / "cache" / "search_cache.json"
CACHE_TTL = 24 * 3600  # Pixabay demande de mettre les réponses en cache 24 h


def _cache_load() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_get(key: str):
    entry = _cache_load().get(key)
    if entry and time.time() - entry["t"] < CACHE_TTL:
        return entry["v"]
    return None


def _cache_set(key: str, value) -> None:
    data = {k: e for k, e in _cache_load().items() if time.time() - e["t"] < CACHE_TTL}
    data[key] = {"t": time.time(), "v": value}
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # le cache est un confort, jamais bloquant


def _resolve_provider(provider: str = None) -> str:
    if provider:
        return provider
    forced = os.getenv("VISUAL_PROVIDER")
    if forced:
        return forced.lower()
    return "pixabay" if os.getenv("PIXABAY_API_KEY") else "pexels"


def _pick_file(video_files: list):
    """Pexels : MP4 portrait, largeur <= 1080, le plus grand possible."""
    mp4 = [f for f in video_files if f.get("file_type") == "video/mp4" and f.get("link")]
    if not mp4:
        return None
    portrait = [f for f in mp4 if (f.get("height") or 0) > (f.get("width") or 0)] or mp4
    fitting = [f for f in portrait if (f.get("width") or 0) <= MAX_WIDTH]
    if fitting:
        return max(fitting, key=lambda f: f.get("width") or 0)
    return min(portrait, key=lambda f: f.get("width") or 0)


def _pick_pixabay_file(videos: dict):
    """Pixabay : plus grande version non vide de largeur <= 1920 (sinon la plus petite)."""
    files = [f for f in (videos or {}).values() if isinstance(f, dict) and f.get("url")]
    if not files:
        return None
    fitting = [f for f in files if (f.get("width") or 0) <= 1920]
    if fitting:
        return max(fitting, key=lambda f: f.get("width") or 0)
    return min(files, key=lambda f: f.get("width") or 0)


def _get(session, url, **kwargs):
    if session is None:
        import requests as session
    try:
        return session.get(url, timeout=20, **kwargs)
    except Exception as exc:
        raise VisualSearchError(f"Connexion impossible : {exc}") from exc


def _check_status(resp, provider: str) -> None:
    if resp.status_code == 200:
        return
    name = provider.capitalize()
    if resp.status_code in (400, 401, 403):
        raise VisualSearchError(f"Clé {name} refusée ({resp.status_code}) : vérifie ta clé dans .env.")
    if resp.status_code == 429:
        raise VisualSearchError(f"Quota {name} atteint (429) : réessaie plus tard.")
    raise VisualSearchError(f"{name} a répondu {resp.status_code}.")


def _search_pexels(query, api_key, per_page, session) -> list:
    resp = _get(session, PEXELS_VIDEO_URL, headers={"Authorization": api_key},
                params={"query": query, "orientation": "portrait", "per_page": per_page})
    _check_status(resp, "pexels")
    candidates = []
    for v in resp.json().get("videos", []):
        file = _pick_file(v.get("video_files", []))
        if not file:
            continue
        candidates.append(
            {
                "provider": "pexels",
                "id": v["id"],
                "page_url": v.get("url"),
                "preview": v.get("image"),
                "duration": v.get("duration"),
                "width": file.get("width"),
                "height": file.get("height"),
                "link": file["link"],
                "author": (v.get("user") or {}).get("name", "inconnu"),
                "author_url": (v.get("user") or {}).get("url"),
            }
        )
    return candidates


def _search_pixabay(query, api_key, per_page, session) -> list:
    resp = _get(session, PIXABAY_VIDEO_URL,
                params={"key": api_key, "q": query[:100], "per_page": max(3, per_page), "safesearch": "true"})
    _check_status(resp, "pixabay")
    candidates = []
    for v in resp.json().get("hits", []):
        file = _pick_pixabay_file(v.get("videos"))
        if not file:
            continue
        preview = file.get("thumbnail") or (
            f"https://i.vimeocdn.com/video/{v['picture_id']}_640x360.jpg" if v.get("picture_id") else None
        )
        candidates.append(
            {
                "provider": "pixabay",
                "id": v["id"],
                "page_url": v.get("pageURL"),
                "preview": preview,
                "duration": v.get("duration"),
                "width": file.get("width"),
                "height": file.get("height"),
                "link": file["url"],
                "author": v.get("user", "inconnu"),
                "author_url": None,
            }
        )
    # Pixabay n'a pas de filtre d'orientation : les vidéos verticales passent en premier
    candidates.sort(key=lambda c: not ((c["height"] or 0) > (c["width"] or 0)))
    return candidates


def search_videos(query: str, api_key: str = None, per_page: int = 6, session=None, provider: str = None) -> list:
    provider = _resolve_provider(provider)
    if provider not in ("pixabay", "pexels"):
        raise VisualSearchError(f"Fournisseur inconnu : {provider}")
    env_name = f"{provider.upper()}_API_KEY"
    api_key = api_key or os.getenv(env_name)
    if not api_key:
        raise VisualSearchError(f"{env_name} absente : renseigne-la dans le fichier .env.")
    cache_key = f"{provider}|{query.strip().lower()}|{per_page}"
    if session is None:  # le cache ne sert que pour les vrais appels réseau
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    search = _search_pixabay if provider == "pixabay" else _search_pexels
    candidates = search(query, api_key, per_page, session)
    if session is None:
        _cache_set(cache_key, candidates)
    return candidates


def download_video(candidate: dict, dest, session=None) -> Path:
    """Télécharge le clip dans dest (.part puis renommage : jamais de fichier à moitié téléchargé)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if session is None:
        import requests as session
    try:
        with session.get(candidate["link"], stream=True, timeout=60) as resp:
            if resp.status_code != 200:
                raise VisualSearchError(f"Téléchargement refusé ({resp.status_code}).")
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    f.write(chunk)
        os.replace(part, dest)
    except VisualSearchError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise VisualSearchError(f"Téléchargement échoué : {exc}") from exc
    return dest


def credit_line(candidate: dict) -> str:
    name = candidate.get("provider", "pexels").capitalize()
    return f"Vidéo : {candidate['author']} sur {name} — {candidate.get('page_url') or name.lower() + '.com'}"


def build_credits(candidates: list) -> str:
    """Texte à coller dans la description YouTube."""
    return "\n".join(dict.fromkeys(credit_line(c) for c in candidates))

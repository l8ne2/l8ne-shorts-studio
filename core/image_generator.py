"""Génération d'images avec Cloudflare Workers AI (FLUX.1 schnell), palier gratuit.

Le modèle renvoie des images carrées 1024x1024 ; `to_vertical` les recadre en 1080x1920.
"""
import base64
import hashlib
import os
import time
from pathlib import Path

CF_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell"
MAX_PROMPT = 2048


class ImageGenerationError(Exception):
    """Erreur lors de la génération d'une image (clés, quota, réseau, réponse invalide)."""


def stable_seed(*parts) -> int:
    """Graine reproductible : mêmes éléments -> même image (changer `attempt` pour une variante)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) + 1


def generate_image(prompt: str, seed: int = None, steps: int = 4, account_id: str = None,
                   token: str = None, session=None, retries: int = 2, sleep=time.sleep) -> bytes:
    """Retourne les octets de l'image (JPEG). `seed` est accepté mais ignoré (non supporté par Cloudflare)."""
    if not prompt.strip():
        raise ImageGenerationError("Le prompt est vide.")
    account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID")
    token = token or os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not token:
        raise ImageGenerationError(
            "CLOUDFLARE_ACCOUNT_ID et CLOUDFLARE_API_TOKEN sont à renseigner dans le fichier .env."
        )
    if session is None:
        import requests as session
    # Cloudflare refuse le paramètre "seed" pour ce modèle (erreur 400) : on n'envoie que prompt et steps.
    # Chaque génération donne donc une image différente, ce qui sert aussi pour les « autres variantes ».
    body = {"prompt": prompt[:MAX_PROMPT], "steps": steps}

    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(CF_URL.format(account=account_id),
                                headers={"Authorization": f"Bearer {token}"}, json=body, timeout=90)
        except Exception as exc:  # réseau, timeout
            last_error = ImageGenerationError(f"Connexion à Cloudflare impossible : {exc}")
        else:
            if resp.status_code in (401, 403):
                raise ImageGenerationError(
                    f"Cloudflare a refusé la clé ({resp.status_code}) : vérifie l'Account ID et le jeton "
                    "(permission Workers AI)."
                )
            if resp.status_code == 429:
                raise ImageGenerationError("Quota gratuit Cloudflare atteint (429) : réessaie demain (00:00 UTC).")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    image_b64 = (data.get("result") or data)["image"]
                    return base64.b64decode(image_b64)
                except Exception as exc:
                    raise ImageGenerationError(f"Réponse Cloudflare invalide : {exc}") from exc
            if resp.status_code < 500:
                raise ImageGenerationError(f"Cloudflare a répondu {resp.status_code} : {resp.text[:200]}")
            last_error = ImageGenerationError(f"Cloudflare indisponible ({resp.status_code}).")
        if attempt < retries:
            sleep(2 * (attempt + 1))
    raise last_error


def save_bytes(data: bytes, dest) -> Path:
    """Écriture atomique (.part puis renommage)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(data)
    os.replace(part, dest)
    return dest


def to_vertical(src, dest, size=(1080, 1920), quality: int = 92) -> Path:
    """Recadre au centre en 9:16 puis redimensionne (ex. carré 1024 -> 1080x1920)."""
    from PIL import Image

    img = Image.open(src).convert("RGB")
    target_ratio = size[0] / size[1]
    w, h = img.size
    if w / h > target_ratio:  # trop large : on coupe les côtés
        new_w = round(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:  # trop haut : on coupe haut et bas
        new_h = round(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    img = img.resize(size, Image.LANCZOS)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=quality)
    return dest

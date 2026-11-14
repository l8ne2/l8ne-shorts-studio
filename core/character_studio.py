"""Studio des personnages : prompts, candidats par émotion, découpe du fond (sprites)."""
import io
from pathlib import Path

from core.image_generator import generate_image, save_bytes, stable_seed
from core.styles import EMOTION_PROMPTS, EMOTIONS, get_style

CHARACTERS_DIR_NAME = "characters"


class CutoutError(Exception):
    """Erreur lors du retrait du fond."""


def character_prompt(style_key: str, description: str, emotion: str) -> str:
    """Prompt d'un personnage seul, sur fond uni, pour pouvoir le découper ensuite."""
    return (
        f"{get_style(style_key)['prompt_prefix']}, character design: {description}. "
        f"{EMOTION_PROMPTS.get(emotion, EMOTION_PROMPTS['neutral'])}. "
        "Full body, standing, centered, the whole character visible, "
        "isolated on a plain flat light grey background, no other objects, no text."
    )


def generate_candidates(character_id: int, style_key: str, description: str, out_dir,
                        emotions=None, per_emotion: int = 2, generator=generate_image) -> dict:
    """Génère per_emotion candidats par émotion. Retourne {emotion: [chemins]}."""
    out_dir = Path(out_dir)
    result = {}
    for emotion in (emotions or EMOTIONS):
        paths = []
        for k in range(per_emotion):
            seed = stable_seed("character", character_id, emotion, k)
            data = generator(character_prompt(style_key, description, emotion), seed=seed)
            paths.append(save_bytes(data, out_dir / f"{emotion}_{k + 1}.jpg"))
        result[emotion] = paths
    return result


def _simple_cutout(img):
    """Retrait de fond sans IA : suppose un fond uni (couleur médiane des bords)."""
    import numpy as np
    from PIL import Image

    rgb = np.asarray(img.convert("RGB")).astype("float32")
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    alpha = np.clip((dist - 28) / 40, 0, 1)  # transition douce : pas de contour dur
    out = Image.fromarray(rgb.astype("uint8"), "RGB").convert("RGBA")
    out.putalpha(Image.fromarray((alpha * 255).astype("uint8"), "L"))
    return out


def remove_background(img, method: str = "auto"):
    """method : 'rembg' (IA, meilleure qualité), 'simple' (fond uni), 'auto' (rembg si installé)."""
    if method in ("auto", "rembg"):
        try:
            from rembg import new_session, remove

            session = new_session(__import__("os").getenv("REMBG_MODEL", "u2netp"))
            return remove(img.convert("RGB"), session=session).convert("RGBA")
        except ImportError:
            if method == "rembg":
                raise CutoutError("rembg n'est pas installé : pip install rembg onnxruntime")
        except Exception as exc:
            if method == "rembg":
                raise CutoutError(f"rembg a échoué : {exc}") from exc
    return _simple_cutout(img)


def make_sprite(src, dest, method: str = "auto", max_height: int = 900) -> Path:
    """Découpe le personnage, rogne les marges transparentes et enregistre un PNG."""
    from PIL import Image

    try:
        img = Image.open(src)
    except Exception as exc:
        raise CutoutError(f"Image illisible : {exc}") from exc
    cut = remove_background(img, method)
    bbox = cut.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    if not bbox:
        raise CutoutError("Aucun personnage détecté : choisis une autre variante.")
    cut = cut.crop(bbox)
    if cut.height > max_height:
        cut = cut.resize((round(cut.width * max_height / cut.height), max_height), Image.LANCZOS)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cut.save(dest, "PNG")
    return dest

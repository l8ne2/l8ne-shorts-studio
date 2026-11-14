"""Génération des illustrations d'un projet (styles non « stock »)."""
import json
from pathlib import Path

from core.config import ROOT
from core.image_generator import generate_image, save_bytes, stable_seed, to_vertical
from core.styles import get_style

IMAGES_DIR = ROOT / "media" / "images"
CREDIT = "Illustrations générées par IA (FLUX.1 schnell via Cloudflare Workers AI)"


def build_scene_prompt(style_key: str, visual: str, character_description: str = None) -> str:
    style = get_style(style_key)
    parts = [style["prompt_prefix"], visual, "vertical composition, no text, no watermark"]
    if style["composition"] in ("sprite", "puppet"):
        parts.append("empty environment, nobody in the scene, space in the lower center for a character")
    elif character_description:
        parts.append(f"featuring this recurring character: {character_description}")
    return ", ".join(p for p in parts if p)


def pick_sprite(expressions: dict, emotion: str):
    """Sprite de l'émotion demandée, sinon neutre, sinon n'importe lequel, sinon None."""
    for key in (emotion, "neutral"):
        path = expressions.get(key)
        if path and Path(path).exists():
            return path
    for path in expressions.values():
        if Path(path).exists():
            return path
    return None


def generate_scene_image(project_id: int, index: int, visual: str, style_key: str,
                         character_description: str = None, out_dir=None, attempt: int = 0,
                         generator=generate_image) -> Path:
    """Génère l'image de la scène `index` (0-based) et retourne le chemin de la version 1080x1920."""
    out_dir = Path(out_dir or IMAGES_DIR / f"project_{project_id}")
    seed = stable_seed("scene", project_id, index, attempt)
    data = generator(build_scene_prompt(style_key, visual, character_description), seed=seed)
    raw = save_bytes(data, out_dir / f"scene_{index + 1}_raw.jpg")
    return to_vertical(raw, out_dir / f"scene_{index + 1}.jpg")


def build_entry(index: int, text: str, plan: dict, image_path, sprite_path, attempt: int = 0,
                animation: dict = None) -> dict:
    return {
        "scene": index + 1, "text": text, "kind": "image", "file": str(image_path),
        "sprite": str(sprite_path) if sprite_path else None,
        "visual": plan["visual"], "emotion": plan["emotion"], "label": plan.get("label", ""),
        "attempt": attempt, "credit": CREDIT, "animation": animation,
    }


def save_plan(entries: list, dest) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest

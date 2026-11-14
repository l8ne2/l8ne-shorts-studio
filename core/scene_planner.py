"""Plan visuel des scènes illustrées (Groq) : décor, émotion du personnage, étiquette à l'écran."""
import json
import re

from core.styles import EMOTIONS, get_style


def _fallback(scenes: list, topic: str) -> list:
    return [{"visual": topic, "emotion": "neutral", "label": ""} for _ in scenes]


def _clean(item: dict) -> dict:
    visual = str(item.get("visual", "")).strip()
    emotion = str(item.get("emotion", "neutral")).strip().lower()
    label = str(item.get("label", "") or "").strip()
    if len(label.split()) > 3:
        label = ""
    return {"visual": visual, "emotion": emotion if emotion in EMOTIONS else "neutral", "label": label}


def plan_scenes(scenes: list, topic: str, style_key: str, character_description: str = None,
                client=None, language: str = "fr"):
    """Retourne (plans, fallback_utilisé) : un dict {visual, emotion, label} par scène."""
    style = get_style(style_key)
    try:
        if client is None:
            import os

            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                return _fallback(scenes, topic), True
            from groq import Groq

            client = Groq(api_key=api_key)
        from core.script_generator import call_groq

        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(scenes))
        sprite_rule = (
            "Décris uniquement le LIEU et l'ambiance : aucun personnage ni humain dans le décor."
            if style["composition"] in ("sprite", "puppet") else
            "Décris la scène complète, avec les éléments importants bien visibles."
        )
        prompt = (
            f"Sujet de la vidéo : {topic}\nStyle visuel : {style['label']}\n"
            + (f"Personnage récurrent : {character_description}\n" if character_description else "")
            + f"\nScènes :\n{numbered}\n\n"
            f"Pour chacune des {len(scenes)} scènes, donne un objet JSON avec :\n"
            f'- "visual" : une phrase EN ANGLAIS (max 25 mots) décrivant ce qu\'on voit, concrète et '
            f"dessinable, sans texte écrit dans l'image. {sprite_rule}\n"
            f'- "emotion" : une valeur parmi {", ".join(EMOTIONS)} (émotion du personnage pendant la scène)\n'
            f'- "label" : un mot ou 3 mots maximum en langue "{language}" nommant l\'élément principal '
            f'montré, ou "" si inutile.\n'
            f"Réponds uniquement avec un tableau JSON de {len(scenes)} objets, sans autre texte."
        )
        content = call_groq(client, [{"role": "user", "content": prompt}], max_tokens=3000,
                            temperature=0.5)
        data = json.loads(re.sub(r"```(?:json)?", "", content).strip())
        if isinstance(data, list) and len(data) == len(scenes) and all(isinstance(d, dict) for d in data):
            plans = [_clean(d) for d in data]
            if all(p["visual"] for p in plans):
                return plans, False
    except Exception:
        pass
    return _fallback(scenes, topic), True

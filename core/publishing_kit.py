"""Kit de publication : titres, description, tags, commentaire épinglé et liste de vérifications."""
import json
import re
from pathlib import Path

from core.styles import uses_ai_images

AI_NOTICE = "Illustrations générées avec l'aide de l'IA."


def _fallback(topic: str) -> dict:
    return {"titles": [topic], "description": topic, "tags": [], "pinned_comment": ""}


def _clean(data: dict, topic: str) -> dict:
    titles = [str(t).strip() for t in data.get("titles", []) if str(t).strip()][:5]
    tags = [str(t).strip().lstrip("#") for t in data.get("tags", []) if str(t).strip()][:12]
    description = str(data.get("description", "")).strip()
    if not titles or not description:
        raise ValueError("kit incomplet")
    return {"titles": titles, "description": description, "tags": tags,
            "pinned_comment": str(data.get("pinned_comment", "")).strip()}


def build_kit(topic: str, script: str, channel_cfg: dict, credits: str = "", style_key: str = "stock",
              client=None):
    """Retourne (kit, repli_utilisé). Le kit contient titles, description, tags, pinned_comment."""
    kit, fallback = None, True
    try:
        if client is None:
            import os

            if not os.getenv("GROQ_API_KEY"):
                raise RuntimeError("clé absente")
            from groq import Groq

            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        from core.script_generator import call_groq

        prompt = (
            f"Chaîne : {channel_cfg['name']} ({channel_cfg.get('niche', '')}), langue : {channel_cfg['language']}.\n"
            f"Sujet : {topic}\n\nScript de la vidéo (YouTube Short) :\n{script}\n\n"
            "Prépare le kit de publication. Réponds uniquement avec un objet JSON ayant ces clés :\n"
            '- "titles" : 5 titres différents, 70 caractères maximum, qui donnent envie de cliquer '
            "sans mentir sur le contenu ;\n"
            '- "description" : 2 à 3 phrases résumant la vidéo, puis 3 hashtags dont #Shorts ;\n'
            '- "tags" : 8 à 12 mots-clés sans #;\n'
            '- "pinned_comment" : une question ouverte qui invite à commenter.\n'
            "N'invente aucun fait absent du script."
        )
        content = call_groq(client, [{"role": "user", "content": prompt}], max_tokens=3000, temperature=0.6)
        match = re.search(r"\{.*\}", re.sub(r"```(?:json)?", "", content), re.S)
        kit, fallback = _clean(json.loads(match.group(0)), topic), False
    except Exception:
        kit = _fallback(topic)
    extra = []
    if credits.strip():
        extra.append(credits.strip())
    if uses_ai_images(style_key):
        extra.append(AI_NOTICE)
    if extra:
        kit["description"] += "\n\n" + "\n".join(extra)
    return kit, fallback


def checklist(project: dict, duration: float = None, credits: str = "", style_key: str = "stock") -> list:
    """Vérifications avant publication : (libellé, état) ; état True = ok, None = à faire par toi."""
    items = [
        ("Script validé", project.get("status") in ("SCRIPT_READY", "AUDIO_READY", "ASSETS_READY", "RENDERING", "COMPLETED")),
        ("Vidéo exportée", project.get("status") == "COMPLETED"),
    ]
    if duration:
        items.append((f"Durée : {duration:.0f} s, format vertical 1080×1920 (vérifie la durée maximale actuelle des Shorts)", True))
    items.append(("Crédits des médias présents dans la description", bool(credits.strip()) or uses_ai_images(style_key)))
    items += [
        ("Faits et chiffres du script vérifiés avec des sources", None),
        ("Droits des visuels vérifiés (conditions de Pixabay/Pexels ou du générateur d'images)", None),
        ("Conditions d'usage commercial de la voix Edge TTS vérifiées", None),
        ("Contenu original et varié (YouTube pénalise le contenu répétitif produit en série)", None),
    ]
    return items


def kit_to_text(kit: dict, items: list) -> str:
    lines = ["TITRES PROPOSÉS"] + [f"{i}. {t}" for i, t in enumerate(kit["titles"], 1)]
    lines += ["", "DESCRIPTION", kit["description"], "", "TAGS", ", ".join(kit["tags"]), "",
              "COMMENTAIRE ÉPINGLÉ", kit["pinned_comment"], "", "AVANT DE PUBLIER"]
    for label, ok in items:
        lines.append(("[x] " if ok else "[ ] ") + label)
    return "\n".join(lines) + "\n"


def save_kit(text: str, video_path) -> Path:
    path = Path(video_path).with_name(Path(video_path).stem + "_kit.txt")
    path.write_text(text, encoding="utf-8")
    return path

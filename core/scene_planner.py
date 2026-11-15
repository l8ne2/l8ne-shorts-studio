"""Plan visuel des scènes illustrées (Groq) : décor, émotion du personnage, étiquette à l'écran."""
import json
import re

from core.styles import EMOTIONS, PUPPET_EMOTIONS, get_style


def _fallback(scenes: list, topic: str) -> list:
    return [{"visual": topic, "emotion": "neutral", "label": "", "type": "puppet"} for _ in scenes]


def _clean(item: dict, allowed=EMOTIONS) -> dict:
    visual = str(item.get("visual", "")).strip()
    emotion = str(item.get("emotion", "neutral")).strip().lower()
    label = str(item.get("label", "") or "").strip()
    if len(label.split()) > 3:
        label = ""
    scene_type = str(item.get("type", "puppet")).strip().lower()
    return {"visual": visual, "emotion": emotion if emotion in allowed else "neutral", "label": label,
            "type": scene_type if scene_type in ("puppet", "illustration") else "puppet"}


def plan_scenes(scenes: list, topic: str, style_key: str, character_description: str = None,
                client=None, language: str = "fr"):
    """Retourne (plans, fallback_utilisé) : un dict {visual, emotion, label} par scène."""
    style = get_style(style_key)
    allowed = PUPPET_EMOTIONS if style["composition"] == "puppet" else EMOTIONS
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
            f'- "emotion" : une valeur parmi {", ".join(allowed)} (émotion du personnage pendant la scène)\n'
            f'- "label" : texte court à afficher à l\'écran (3 mots maximum, langue "{language}") : nom de '
            f'l\'élément montré, mot-clé fort ou chronomètre, ou "" si inutile.\n'
            + ('- "type" : "puppet" (le personnage dessiné parle devant le décor) ou "illustration" (moment '
               'dramatique ou émotionnel montré en grand avec le personnage dans la scène ; 1 scène sur 3 '
               'maximum, jamais la première).\n' if style["composition"] == "puppet" else "")
            +
            f"Réponds uniquement avec un tableau JSON de {len(scenes)} objets, sans autre texte."
        )
        content = call_groq(client, [{"role": "user", "content": prompt}], max_tokens=3000,
                            temperature=0.5)
        data = json.loads(re.sub(r"```(?:json)?", "", content).strip())
        if isinstance(data, list) and len(data) == len(scenes) and all(isinstance(d, dict) for d in data):
            plans = [_clean(d, allowed) for d in data]
            if all(p["visual"] for p in plans):
                return plans, False
    except Exception:
        pass
    return _fallback(scenes, topic), True


def plan_dialogue_scenes(scenes: list, topic: str, speakers: list, client=None, language: str = "fr"):
    """Plan visuel d'un dialogue. scenes : [{'text', ...}] (répliques regroupées).

    Retourne (plans, repli_utilisé) ; chaque plan : {visual, emotions: [émotion A, émotion B], label, type}.
    """
    allowed = PUPPET_EMOTIONS

    def fallback():
        return [{"visual": topic, "emotions": ["neutral", "neutral"], "label": "", "type": "puppet"} for _ in scenes]

    try:
        if client is None:
            import os

            if not os.getenv("GROQ_API_KEY"):
                return fallback(), True
            from groq import Groq

            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        from core.script_generator import call_groq

        numbered = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(scenes))
        a, b = speakers[0]["name"], speakers[1]["name"]
        prompt = (
            f"Sujet de la vidéo : {topic}\nDeux personnages discutent : {a} et {b}.\n\nScènes (extraits du dialogue) :\n"
            f"{numbered}\n\n"
            f"Pour chacune des {len(scenes)} scènes, donne un objet JSON avec :\n"
            '- "visual" : une phrase EN ANGLAIS (max 25 mots) décrivant le LIEU et l\'ambiance, sans personnage '
            "ni texte écrit dans l'image ;\n"
            f'- "emotions" : une liste de 2 valeurs [émotion de {a}, émotion de {b}] parmi {", ".join(allowed)} ;\n'
            f'- "label" : texte court à afficher à l\'écran (3 mots maximum, langue "{language}") ou "" ;\n'
            '- "type" : "puppet" (les deux personnages dessinés devant le décor) ou "illustration" (moment '
            "dramatique montré en grand dans une image complète ; 1 scène sur 3 maximum, jamais la première).\n"
            f"Réponds uniquement avec un tableau JSON de {len(scenes)} objets, sans autre texte."
        )
        content = call_groq(client, [{"role": "user", "content": prompt}], max_tokens=3500, temperature=0.5)
        data = json.loads(re.sub(r"```(?:json)?", "", content).strip())
        if isinstance(data, list) and len(data) == len(scenes) and all(isinstance(d, dict) for d in data):
            plans = []
            for d in data:
                emos = d.get("emotions") if isinstance(d.get("emotions"), list) else []
                emos = [str(e).strip().lower() for e in (emos + ["neutral", "neutral"])[:2]]
                plan = _clean(d, allowed)
                plan["emotions"] = [e if e in allowed else "neutral" for e in emos]
                plans.append(plan)
            if all(p["visual"] for p in plans):
                return plans, False
    except Exception:
        pass
    return fallback(), True

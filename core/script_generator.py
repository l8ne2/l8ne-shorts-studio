"""Génération du script d'un Short avec l'API Groq (Phase 2)."""
import os
import re

WORDS_PER_SECOND = 2.5  # débit approximatif de narration en français
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class ScriptGenerationError(Exception):
    """Erreur lors de la génération du script (clé absente, API, réponse vide...)."""


def target_words(duration_s: int) -> int:
    return int(duration_s * WORDS_PER_SECOND)


def build_messages(topic: str, channel_cfg: dict) -> list:
    style = channel_cfg.get("style", {})
    words = target_words(channel_cfg["duration"])
    system = (
        "Tu es scénariste de YouTube Shorts. Tu écris uniquement le texte de la voix off, "
        "prêt à être lu à voix haute : pas de titre, pas de didascalies, pas d'émojis, "
        "pas de markdown, pas de numérotation de scènes."
    )
    user = (
        f"Chaîne : {channel_cfg['name']} ({channel_cfg.get('niche', '')})\n"
        f"Langue : {channel_cfg['language']}\n"
        f"Ton : {style.get('tone', 'neutre')} ; narration : {style.get('narration', 'classique')}\n"
        f"Durée visée : {channel_cfg['duration']} secondes, soit environ {words} mots.\n\n"
        f"Sujet : {topic}\n\n"
        "Structure : une accroche forte dans la première phrase, un développement "
        "clair avec des phrases courtes, puis une conclusion ou une question finale.\n"
        "Règles : n'invente aucun fait, chiffre ou date ; si une information est incertaine "
        "ou hypothétique, dis-le explicitement."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def clean_script(text: str) -> str:
    text = re.sub(r"[*_#`]+", "", text)
    return text.strip().strip('"«»').strip()


def generate_script(topic: str, channel_cfg: dict, client=None, model: str = None) -> str:
    """Retourne le script généré. `client` est injectable pour les tests."""
    if not topic.strip():
        raise ScriptGenerationError("Le sujet est vide.")
    if client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ScriptGenerationError("GROQ_API_KEY absente : renseigne-la dans le fichier .env.")
        from groq import Groq  # import tardif : inutile pour les tests

        client = Groq(api_key=api_key)
    model = model or os.getenv("GROQ_MODEL") or DEFAULT_MODEL
    try:
        response = client.chat.completions.create(
            model=model,
            messages=build_messages(topic, channel_cfg),
            temperature=0.7,
            max_tokens=700,
        )
        text = response.choices[0].message.content or ""
    except Exception as exc:  # erreurs réseau, quota (429), modèle retiré...
        raise ScriptGenerationError(f"Appel Groq échoué : {exc}") from exc
    script = clean_script(text)
    if not script:
        raise ScriptGenerationError("Groq a renvoyé une réponse vide.")
    return script


def check_script(script: str, duration_s: int) -> list:
    """Contrôle qualité simple : retourne une liste d'avertissements."""
    warnings = []
    words = script.split()
    target = target_words(duration_s)
    if len(words) < target * 0.7:
        warnings.append(f"Script court : {len(words)} mots pour ~{target} visés.")
    if len(words) > target * 1.3:
        warnings.append(f"Script long : {len(words)} mots pour ~{target} visés.")
    sentences = [s.strip().lower() for s in re.split(r"[.!?]+", script) if s.strip()]
    if len(sentences) != len(set(sentences)):
        warnings.append("Des phrases sont répétées.")
    return warnings

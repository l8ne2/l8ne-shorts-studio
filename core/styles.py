"""Styles visuels des vidéos et émotions des personnages.

Un style décrit comment les images sont générées et assemblées :
- composition "stock"      : vidéos de banque libre (Pixabay), comme avant ;
- composition "full_scene" : une illustration complète par scène (le personnage, s'il y en a un,
                             est décrit dans le prompt) ;
- composition "sprite"     : un décor généré par scène + le personnage découpé, posé et animé dessus ;
- composition "puppet"     : un décor généré + un personnage dessiné par code, animé au rythme de la voix.
"""

EMOTIONS = ["neutral", "surprised", "happy", "angry", "sad", "thinking"]
EMOTION_LABELS = {
    "neutral": "Neutre", "surprised": "Surpris", "happy": "Content",
    "angry": "Énervé", "sad": "Triste", "thinking": "Réfléchit",
}
EMOTION_PROMPTS = {
    "neutral": "calm neutral expression, relaxed pose",
    "surprised": "shocked expression, wide open eyes and mouth, hands raised",
    "happy": "big happy smile, joyful pose",
    "angry": "angry frown, clenched fists",
    "sad": "sad worried expression, slumped shoulders",
    "thinking": "thoughtful expression, hand on chin, looking up",
}

STYLES = {
    "stock": {
        "label": "Vidéos de stock (Pixabay)",
        "composition": "stock",
        "characters": False,
        "labels": False,
        "prompt_prefix": "",
        "description": "Vidéos libres de droits illustrant le script. Pas d'IA d'images.",
    },
    "cartoon_2d": {
        "label": "Dessin animé 2D raconté",
        "composition": "full_scene",
        "characters": True,
        "labels": False,
        "prompt_prefix": ("flat 2D cartoon illustration, bold clean outlines, warm saturated colors, "
                          "storybook animation style, expressive characters"),
        "description": "Une illustration de dessin animé par scène, animée par la caméra.",
    },
    "puppet_2d": {
        "label": "Marionnette 2D animée (dessin animé parlant)",
        "composition": "puppet",
        "characters": True,
        "labels": False,
        "prompt_prefix": ("flat 2D cartoon background illustration, bold clean outlines, warm saturated colors, "
                          "simple stylized shapes, wide scenic landscape"),
        "description": ("Un personnage dessiné qui parle (bouche synchronisée sur la voix), change d'expression "
                        "et bouge devant des décors animés."),
    },
    "game_3d": {
        "label": "Personnage 3D coloré (style jeu)",
        "composition": "sprite",
        "characters": True,
        "labels": False,
        "prompt_prefix": ("colorful 3D render, blocky toy-like video game style, bright saturated colors, "
                          "soft studio lighting, glossy plastic materials, cute and funny"),
        "description": "Un personnage récurrent posé sur des décors générés, avec expressions.",
    },
    "cutaway_3d": {
        "label": "Explication 3D en coupe",
        "composition": "full_scene",
        "characters": False,
        "labels": True,
        "prompt_prefix": ("3D render cutaway cross-section view, clean bright colors, soft lighting, "
                          "educational diorama, grass and soil layers visible"),
        "description": "Scènes pédagogiques en coupe, avec étiquettes à l'écran.",
    },
}

DEFAULT_STYLE = "stock"


def get_style(key: str) -> dict:
    return STYLES.get(key, STYLES[DEFAULT_STYLE])


def uses_ai_images(key: str) -> bool:
    return get_style(key)["composition"] != "stock"

"""Ambiances visuelles (« looks ») : décors, étalonnage de l'image et sous-titres d'une vidéo.

Un look s'ajoute au style (marionnette, 3D...) sans le remplacer : il change l'ambiance des décors générés,
la teinte finale de la vidéo (grain, bords sombres, couleurs) et le style des sous-titres.
"""

LOOKS = {
    "pop_clair": {
        "label": "Pop clair (Tech & IA)",
        "bg_prefix": "clean modern flat illustration, bright vivid colors, soft gradients, minimal tech aesthetic",
        "grade": "eq=saturation=1.08:contrast=1.04",
        "subtitles": "modernes",
    },
    "thriller_sombre": {
        "label": "Thriller sombre (Mystères)",
        "bg_prefix": ("dark moody cartoon illustration, deep shadows, desaturated greens and greys, "
                      "ominous atmosphere, strong contrast, dim eerie lighting"),
        "grade": "eq=contrast=1.12:saturation=0.85:brightness=-0.05,vignette=PI/4,noise=alls=7:allf=t",
        "subtitles": "marqués",
    },
    "nuit_cosy": {
        "label": "Nuit cosy (histoires calmes)",
        "bg_prefix": ("cozy painterly illustration, warm lamp light against blue night tones, "
                      "soft hand-painted textures, detailed room interior, quiet mood"),
        "grade": "colorbalance=rs=.04:bs=-.03,vignette=PI/6",
        "subtitles": "modernes",
    },
    "chaud_colore": {
        "label": "Chaud et coloré (Cinéma & séries)",
        "bg_prefix": ("warm vibrant cartoon illustration, golden hour light, rich saturated oranges and teals, "
                      "cinematic composition"),
        "grade": "eq=saturation=1.15:contrast=1.06,colorbalance=rs=.03:bs=-.03",
        "subtitles": "dynamiques",
    },
}

NEUTRAL = {"label": "Standard", "bg_prefix": "", "grade": "", "subtitles": None}
AUTO = "auto"  # « selon la chaîne »


def resolve_look(project_look: str, channel_cfg: dict) -> dict:
    """Look effectif d'un projet : celui choisi, sinon celui de la chaîne, sinon neutre."""
    key = project_look if project_look and project_look != AUTO else channel_cfg.get("look")
    return LOOKS.get(key, NEUTRAL)

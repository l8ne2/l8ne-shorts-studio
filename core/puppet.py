"""Personnage « marionnette » 2D dessiné par code.

Le personnage est composé de parties (tête, yeux, bouche, corps, bras, jambes) : on peut donc changer
d'expression, ouvrir la bouche au rythme de la voix, cligner des yeux, lever un bras...
Trois corps : « dressed » (habillé), « stick » (bonhomme bâton) et « cozy » (petit pull mignon).
Tout est dessiné avec Pillow : aucune image IA, aucun quota, rendu instantané.
"""
import json
import math
from dataclasses import asdict, dataclass, fields

from PIL import Image, ImageChops, ImageDraw, ImageFilter

DEFAULT_OUTLINE = "#261b16"
SS = 2                      # suréchantillonnage pour des contours lisses
CANVAS = (600, 1000)        # taille de dessin (avant mise à l'échelle)
HATS = ("none", "cap", "beanie", "helmet", "hair")
BODIES = ("dressed", "stick", "cozy")
MOUTH_LEVELS = 4            # 0 = fermée ... 3 = grande ouverte
FACE_SCALE = 1.4            # le visage est agrandi : lisible sur un écran de téléphone
HEAD_BOX = (105, 55, 495, 445)


@dataclass
class PuppetDesign:
    skin: str = "#f5cf9d"
    outfit: str = "#6b7a3a"
    pants: str = "#4a4a3a"
    hat: str = "cap"
    hat_color: str = "#7a5a2a"
    hair: str = "#3b2a1a"
    belt: bool = True
    body: str = "dressed"
    outline: str = DEFAULT_OUTLINE
    line_scale: float = 1.0     # épaisseur des traits (0,7 fin ... 1,8 épais)
    shading: bool = False       # ombrage doux sur la tête
    blush: bool = False         # joues roses

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "PuppetDesign":
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        names = {f.name for f in fields(cls)}
        design = cls(**{k: v for k, v in data.items() if k in names})
        if design.hat not in HATS:
            design.hat = "none"
        if design.body not in BODIES:
            design.body = "dressed"
        try:
            design.line_scale = min(max(float(design.line_scale), 0.5), 2.0)
        except (TypeError, ValueError):
            design.line_scale = 1.0
        return design


PRESETS = {
    "soldier": ("Soldat (par défaut)", PuppetDesign()),
    "classic_stick": ("Bonhomme bâton classique", PuppetDesign(
        body="stick", skin="#ffffff", outfit="#ffffff", pants="#1f2a5a", hat="none", belt=False,
        outline="#1b2250", line_scale=1.4, shading=True, blush=False)),
    "cozy_beige": ("Cosy beige et crème", PuppetDesign(
        body="cozy", skin="#fdf3e3", outfit="#e6d3b3", pants="#c9b196", hat="none", hair="#6b4f3a", belt=False,
        outline="#6a5240", line_scale=0.85, shading=True, blush=True)),
}


def _rgba(hex_color: str, alpha: int = 255):
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        h = "888888"
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)
    except ValueError:
        return (136, 136, 136, alpha)


def _darker(color, factor: float = 0.82):
    return tuple(int(c * factor) for c in color[:3])


def _eyes_and_brows(d, emotion: str, blink: bool, s: int, ol, k: float):
    lx, rx, y = 225 * s, 375 * s, 255 * s
    w = round(12 * k) * s  # épaisseur des traits
    if blink and emotion not in ("happy", "relaxed"):
        for x in (lx, rx):
            d.line((x - 20 * s, y, x + 20 * s, y), fill=ol, width=w)
        return
    if emotion == "happy":  # yeux fermés « ^ ^ »
        for x in (lx, rx):
            d.arc((x - 26 * s, y - 22 * s, x + 26 * s, y + 30 * s), 200, 340, fill=ol, width=w)
        return
    if emotion == "relaxed":  # yeux fermés paisibles « u u »
        for x in (lx, rx):
            d.arc((x - 24 * s, y - 24 * s, x + 24 * s, y + 18 * s), 20, 160, fill=ol, width=w)
        return
    if emotion == "tired":  # lourdes paupières, regard bas
        for x in (lx, rx):
            d.ellipse((x - 14 * s, y - 2 * s, x + 14 * s, y + 24 * s), fill=ol)
            d.line((x - 30 * s, y - 4 * s, x + 30 * s, y - 4 * s), fill=ol, width=w + 2 * s)
        return
    if emotion == "surprised":  # grands yeux blancs
        for x in (lx, rx):
            d.ellipse((x - 34 * s, y - 38 * s, x + 34 * s, y + 38 * s), fill=(255, 255, 255, 255),
                      outline=ol, width=8 * s)
            d.ellipse((x - 9 * s, y - 9 * s, x + 9 * s, y + 9 * s), fill=ol)
        d.line((lx - 34 * s, y - 70 * s, lx + 30 * s, y - 78 * s), fill=ol, width=w)
        d.line((rx - 30 * s, y - 78 * s, rx + 34 * s, y - 70 * s), fill=ol, width=w)
        return
    look_up = -10 * s if emotion == "thinking" else 0
    for x in (lx, rx):
        d.ellipse((x - 15 * s, y + look_up - 17 * s, x + 15 * s, y + look_up + 17 * s), fill=ol)
    if emotion == "angry":  # sourcils en V
        d.line((lx - 40 * s, y - 62 * s, lx + 32 * s, y - 28 * s), fill=ol, width=w + 2 * s)
        d.line((rx + 40 * s, y - 62 * s, rx - 32 * s, y - 28 * s), fill=ol, width=w + 2 * s)
    elif emotion == "sad":  # sourcils tombants
        d.line((lx - 36 * s, y - 28 * s, lx + 32 * s, y - 56 * s), fill=ol, width=w)
        d.line((rx + 36 * s, y - 28 * s, rx - 32 * s, y - 56 * s), fill=ol, width=w)
    elif emotion == "thinking":  # un sourcil levé
        d.line((lx - 34 * s, y - 52 * s, lx + 34 * s, y - 52 * s), fill=ol, width=w)
        d.line((rx - 34 * s, y - 78 * s, rx + 34 * s, y - 66 * s), fill=ol, width=w)


def _mouth(d, emotion: str, level: int, s: int, ol, k: float):
    cx, y = 300 * s, 342 * s
    w = round(11 * k) * s
    if level > 0:  # bouche qui parle : ovale plus ou moins ouvert
        h = (14, 34, 62)[min(level, 3) - 1] * s
        half = (30, 36, 42)[min(level, 3) - 1] * s
        d.ellipse((cx - half, y - h // 2, cx + half, y + h // 2), fill=(70, 25, 25, 255), outline=ol, width=8 * s)
        if level == 3:
            d.ellipse((cx - 22 * s, y + 4 * s, cx + 22 * s, y + h // 2 - 2 * s), fill=(214, 96, 96, 255))
        return
    if emotion == "happy":
        d.pieslice((cx - 44 * s, y - 32 * s, cx + 44 * s, y + 36 * s), 0, 180, fill=(255, 255, 255, 255),
                   outline=ol, width=8 * s)
    elif emotion == "relaxed":
        d.arc((cx - 38 * s, y - 22 * s, cx + 38 * s, y + 26 * s), 20, 160, fill=ol, width=w)
    elif emotion == "tired":
        d.line((cx - 16 * s, y + 8 * s, cx + 26 * s, y + 2 * s), fill=ol, width=w)
    elif emotion in ("sad", "angry"):
        d.arc((cx - 36 * s, y - 6 * s, cx + 36 * s, y + 40 * s), 200, 340, fill=ol, width=w)
    elif emotion == "surprised":
        d.ellipse((cx - 20 * s, y - 24 * s, cx + 20 * s, y + 28 * s), fill=(70, 25, 25, 255), outline=ol, width=8 * s)
    elif emotion == "thinking":
        d.line((cx - 20 * s, y + 4 * s, cx + 30 * s, y - 8 * s), fill=ol, width=w)
    else:
        d.line((cx - 30 * s, y, cx + 30 * s, y), fill=ol, width=w)


def _hat(d, design, s: int, ol):
    col, cx, top = _rgba(design.hat_color), 300 * s, 70 * s
    if design.hat == "cap":
        d.pieslice((120 * s, 60 * s, 480 * s, 400 * s), 180, 360, fill=col, outline=ol, width=9 * s)
        d.ellipse((290 * s, 196 * s, 565 * s, 252 * s), fill=col, outline=ol, width=8 * s)
    elif design.hat == "beanie":
        d.pieslice((125 * s, 62 * s, 475 * s, 400 * s), 180, 360, fill=col, outline=ol, width=9 * s)
        d.rounded_rectangle((128 * s, 190 * s, 472 * s, 232 * s), 18 * s, fill=col, outline=ol, width=8 * s)
        d.ellipse((cx - 24 * s, top - 40 * s, cx + 24 * s, top + 8 * s), fill=col, outline=ol, width=7 * s)
    elif design.hat == "helmet":
        d.pieslice((112 * s, 52 * s, 488 * s, 420 * s), 180, 360, fill=col, outline=ol, width=9 * s)
        d.rectangle((110 * s, 214 * s, 490 * s, 236 * s), fill=col, outline=ol, width=7 * s)
        d.ellipse((cx - 16 * s, 118 * s, cx + 16 * s, 150 * s), fill=(240, 200, 80, 255), outline=ol, width=6 * s)
    elif design.hat == "hair":
        hair = _rgba(design.hair)
        pts = [(140, 200), (130, 120), (190, 150), (230, 60), (290, 130), (350, 50), (400, 140), (470, 110), (460, 200)]
        d.polygon([(x * s, y * s) for x, y in pts], fill=hair, outline=ol)
        d.line([(x * s, y * s) for x, y in pts] + [(140 * s, 200 * s)], fill=ol, width=8 * s, joint="curve")


def _arm_points(arm_raise: float, s: int, shoulder=(395, 480)):
    """Épaule, coude et main du bras animé. Au repos le bras pend ; levé, le coude part sur le côté et
    l'avant-bras remonte (geste de salut) sans toucher la tête."""
    t = arm_raise ** 1.3
    upper = math.radians(20 + 65 * t)     # angle depuis la verticale vers le bas
    fore = math.radians(20 + 120 * t)
    sx, sy = shoulder
    ex, ey = sx + math.sin(upper) * 120, sy + math.cos(upper) * 120
    hx, hy = ex + math.sin(fore) * 100, ey + math.cos(fore) * 100
    return (sx * s, sy * s), (ex * s, ey * s), (hx * s, hy * s)


def _body_dressed(d, design, s, ol, k, arm_raise, walk, skin):
    line = round(12 * k) * s
    for hip, sign in ((262, -1), (338, 1)):
        foot_x = hip + sign * 14 + walk * sign * 34
        d.line((hip * s, 705 * s, foot_x * s, 925 * s), fill=ol, width=line)
        d.ellipse(((foot_x - 30) * s, 910 * s, (foot_x + 30) * s, 942 * s), fill=ol)
    left_hand = (178 * s, 690 * s)
    d.line((205 * s, 480 * s, 165 * s, 600 * s, left_hand[0], left_hand[1]), fill=ol, width=line, joint="curve")
    a, e, h = _arm_points(arm_raise, s)
    d.line((*a, *e, *h), fill=ol, width=line, joint="curve")
    for hand in (left_hand, h):
        d.ellipse((hand[0] - 20 * s, hand[1] - 20 * s, hand[0] + 20 * s, hand[1] + 20 * s), fill=skin, outline=ol, width=7 * s)
    d.rounded_rectangle((190 * s, 430 * s, 410 * s, 720 * s), 46 * s, fill=_rgba(design.outfit), outline=ol, width=round(10 * k) * s)
    if design.belt:
        d.rectangle((192 * s, 640 * s, 408 * s, 668 * s), fill=_rgba(design.pants), outline=ol, width=6 * s)
        d.rectangle((282 * s, 637 * s, 318 * s, 671 * s), fill=(240, 200, 80, 255), outline=ol, width=5 * s)
    d.line((235 * s, 440 * s, 365 * s, 585 * s), fill=ol, width=8 * s)  # bandoulière


def _body_stick(d, design, s, ol, k, arm_raise, walk, skin):
    line = round(13 * k) * s
    for sign in (-1, 1):  # jambes fines
        foot_x = 300 + sign * 55 + walk * sign * 34
        d.line((300 * s, 700 * s, (300 + sign * 40) * s, 810 * s, foot_x * s, 925 * s), fill=ol, width=line, joint="curve")
        d.ellipse(((foot_x - 26) * s, 912 * s, (foot_x + 26) * s, 940 * s), fill=ol)
    d.line((300 * s, 430 * s, 300 * s, 705 * s), fill=ol, width=line)  # colonne
    d.line((300 * s, 500 * s, 245 * s, 585 * s, 215 * s, 680 * s), fill=ol, width=line, joint="curve")
    a, e, h = _arm_points(arm_raise, s, shoulder=(300, 500))
    d.line((*a, *e, *h), fill=ol, width=line, joint="curve")
    for hand in ((215 * s, 680 * s), h):  # petites mains pleines, comme les bonhommes bâtons classiques
        d.ellipse((hand[0] - 21 * s, hand[1] - 21 * s, hand[0] + 21 * s, hand[1] + 21 * s), fill=ol)


def _body_cozy(d, design, s, ol, k, arm_raise, walk, skin):
    out, pants, sweater = round(9 * k) * s, _rgba(design.pants), _rgba(design.outfit)
    for cx_, sign in ((262, -1), (338, 1)):  # jambes : pantalon rond + petite chaussure
        foot = cx_ + sign * 8 + walk * sign * 30
        d.rounded_rectangle(((foot - 30) * s, 650 * s, (foot + 30) * s, 905 * s), 28 * s, fill=pants, outline=ol, width=out)
        d.ellipse(((foot - 38) * s, 888 * s, (foot + 38) * s, 940 * s), fill=_rgba("#8a6f58"), outline=ol, width=out)
    # bras : manche (trait épais) + main
    def sleeve(points):
        d.line(points, fill=ol, width=round(46 * k) * s, joint="curve")
        d.line(points, fill=sweater, width=round(46 * k) * s - 2 * out, joint="curve")
    sleeve((212 * s, 500 * s, 175 * s, 600 * s, 168 * s, 670 * s))
    a, e, h = _arm_points(arm_raise, s, shoulder=(388, 500))
    sleeve((*a, *e, *h))
    for hand in ((168 * s, 676 * s), h):
        d.ellipse((hand[0] - 22 * s, hand[1] - 22 * s, hand[0] + 22 * s, hand[1] + 22 * s), fill=skin, outline=ol, width=out)
    d.rounded_rectangle((195 * s, 435 * s, 405 * s, 700 * s), 78 * s, fill=sweater, outline=ol, width=out)
    d.line((215 * s, 668 * s, 385 * s, 668 * s), fill=_rgba(design.pants, 90), width=5 * s)  # bord du pull


BODY_DRAWERS = {"dressed": _body_dressed, "stick": _body_stick, "cozy": _body_cozy}


def _shade_head(img: Image.Image, skin, s: int) -> None:
    """Ombre douce en croissant en bas à droite + reflet en haut à gauche (lumière venant du haut-gauche)."""
    x0, y0, x1, y1 = (v * s for v in HEAD_BOX)
    inset = 14 * s
    box = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    off = Image.new("L", img.size, 0)
    ImageDraw.Draw(off).ellipse((box[0] - 55 * s, box[1] - 55 * s, box[2] - 55 * s, box[3] - 55 * s), fill=255)
    crescent = ImageChops.subtract(mask, off).filter(ImageFilter.GaussianBlur(10 * s))
    shade = Image.new("RGBA", img.size, _darker(skin, 0.78) + (0,))
    shade.putalpha(crescent.point(lambda v: v * 95 // 255))
    img.alpha_composite(shade)
    glow = Image.new("RGBA", img.size, (255, 255, 255, 0))  # base blanche : le flou ne crée pas de halo gris
    ImageDraw.Draw(glow).ellipse((165 * s, 105 * s, 250 * s, 165 * s), fill=(255, 255, 255, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12 * s)))


def draw_puppet(design: PuppetDesign, emotion: str = "neutral", mouth: int = 0, blink: bool = False,
                arm_raise: float = 0.0, walk: float = 0.0, display_height: int = 820) -> Image.Image:
    """Dessine le personnage (RGBA, fond transparent) à la hauteur voulue.

    mouth : 0 (fermée) à 3 (grande ouverte) ; arm_raise : 0 (bras le long du corps) à 1 (bras levé) ;
    walk : -1 à 1, écarte les jambes (marche).
    """
    s = SS
    k = design.line_scale
    ol = _rgba(design.outline)
    img = Image.new("RGBA", (CANVAS[0] * s, CANVAS[1] * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin = _rgba(design.skin)
    BODY_DRAWERS.get(design.body, _body_dressed)(d, design, s, ol, k, arm_raise, walk, skin)
    d.ellipse(tuple(v * s for v in HEAD_BOX), fill=skin, outline=ol, width=round(11 * k) * s)  # tête
    if design.shading:
        _shade_head(img, skin, s)
        d = ImageDraw.Draw(img)
    if design.blush:
        cheeks = Image.new("RGBA", img.size, (240, 130, 130, 0))
        cd = ImageDraw.Draw(cheeks)
        for cx_ in (172, 428):
            cd.ellipse(((cx_ - 34) * s, 322 * s, (cx_ + 34) * s, 358 * s), fill=(240, 130, 130, 120))
        img.alpha_composite(cheeks.filter(ImageFilter.GaussianBlur(5 * s)))
        d = ImageDraw.Draw(img)
    if design.body != "stick":  # petit nez (le bonhomme bâton classique n'en a pas)
        d.ellipse((276 * s, 292 * s, 324 * s, 330 * s), fill=_rgba("#e8b27f") if design.body == "dressed" else _darker(skin, 0.92) + (255,))
    face = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)
    _eyes_and_brows(fd, emotion, blink, s, ol, k)
    _mouth(fd, emotion, mouth, s, ol, k)
    box = (140 * s, 150 * s, 460 * s, 430 * s)
    region = face.crop(box)
    region = region.resize((round(region.width * FACE_SCALE), round(region.height * FACE_SCALE)), Image.LANCZOS)
    cx, cy = (box[0] + box[2]) // 2, 305 * s
    img.alpha_composite(region, (cx - region.width // 2, cy - region.height // 2))
    if design.hat != "none":
        _hat(ImageDraw.Draw(img), design, s, ol)
    bbox = img.getbbox()
    img = img.crop(bbox) if bbox else img
    ratio = display_height / img.height      # le personnage mesure exactement display_height de haut
    size = (max(1, round(img.width * ratio)), display_height)
    return img.resize(size, Image.LANCZOS)


_COLOR_NAMES = {
    "black": (20, 20, 20), "white": (250, 250, 250), "cream": (253, 243, 227), "beige": (230, 211, 179),
    "grey": (128, 128, 128), "red": (200, 40, 40), "orange": (240, 140, 40), "yellow": (240, 210, 60),
    "green": (60, 160, 70), "olive green": (107, 122, 58), "blue": (50, 100, 200), "navy blue": (30, 40, 90),
    "purple": (130, 70, 170), "pink": (240, 150, 190), "brown": (110, 70, 40), "dark brown": (70, 45, 30),
    "tan": (210, 170, 120), "peach": (245, 207, 157),
}


def color_name(hex_color: str) -> str:
    """Nom anglais approximatif d'une couleur (pour les prompts d'images)."""
    r, g, b = _rgba(hex_color)[:3]
    return min(_COLOR_NAMES, key=lambda n: sum((a - c) ** 2 for a, c in zip((r, g, b), _COLOR_NAMES[n])))


def describe_design(design: PuppetDesign) -> str:
    """Description anglaise du personnage, pour le dessiner dans une image générée par IA."""
    hats = {
        "none": "no hat", "cap": f"a {color_name(design.hat_color)} cap",
        "beanie": f"a {color_name(design.hat_color)} beanie", "helmet": f"a {color_name(design.hat_color)} helmet",
        "hair": f"{color_name(design.hair)} spiky hair",
    }
    head = (f"a cute cartoon stickman character with a big perfectly round {color_name(design.skin)} head and "
            f"thick {color_name(design.outline)} outlines, {hats.get(design.hat, 'no hat')}")
    if design.body == "stick":
        return head + ", thin stick-figure body with simple line arms and legs, no clothes, simple dot eyes"
    if design.body == "cozy":
        return (head + f", wearing a soft {color_name(design.outfit)} sweater and {color_name(design.pants)} pants, "
                "short simple limbs, simple dot eyes, gentle friendly look")
    return (head + f", wearing a {color_name(design.outfit)} shirt, thin black stick arms and legs, simple dot eyes")

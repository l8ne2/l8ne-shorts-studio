"""Personnage « marionnette » 2D dessiné par code (grosse tête ronde, membres fins).

Le personnage est composé de parties (tête, yeux, bouche, corps, bras, jambes) : on peut donc
changer d'expression, ouvrir la bouche au rythme de la voix, cligner des yeux, lever un bras...
Tout est dessiné avec Pillow : aucune image IA, aucun quota, rendu instantané.
"""
import json
import math
from dataclasses import asdict, dataclass, fields

from PIL import Image, ImageDraw

OUTLINE = (38, 27, 22, 255)
SS = 2                      # suréchantillonnage pour des contours lisses
CANVAS = (600, 1000)        # taille de dessin (avant mise à l'échelle)
HATS = ("none", "cap", "beanie", "helmet", "hair")
MOUTH_LEVELS = 4            # 0 = fermée ... 3 = grande ouverte
FACE_SCALE = 1.4            # le visage est agrandi : lisible sur un écran de téléphone


@dataclass
class PuppetDesign:
    skin: str = "#f5cf9d"
    outfit: str = "#6b7a3a"
    pants: str = "#4a4a3a"
    hat: str = "cap"
    hat_color: str = "#7a5a2a"
    hair: str = "#3b2a1a"
    belt: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> "PuppetDesign":
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        design = cls(**{k: v for k, v in data.items() if k in names})
        if design.hat not in HATS:
            design.hat = "none"
        return design


def _rgba(hex_color: str, alpha: int = 255):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "888888"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _eyes_and_brows(d, emotion: str, blink: bool, s: int):
    lx, rx, y = 225 * s, 375 * s, 255 * s
    w = 12 * s  # épaisseur des traits
    if blink and emotion not in ("happy",):
        for x in (lx, rx):
            d.line((x - 20 * s, y, x + 20 * s, y), fill=OUTLINE, width=w)
        return
    if emotion == "happy":  # yeux fermés « ^ ^ »
        for x in (lx, rx):
            d.arc((x - 26 * s, y - 22 * s, x + 26 * s, y + 30 * s), 200, 340, fill=OUTLINE, width=w)
        return
    if emotion == "surprised":  # grands yeux blancs
        for x in (lx, rx):
            d.ellipse((x - 34 * s, y - 38 * s, x + 34 * s, y + 38 * s), fill=(255, 255, 255, 255),
                      outline=OUTLINE, width=8 * s)
            d.ellipse((x - 9 * s, y - 9 * s, x + 9 * s, y + 9 * s), fill=OUTLINE)
        d.line((lx - 34 * s, y - 70 * s, lx + 30 * s, y - 78 * s), fill=OUTLINE, width=w)
        d.line((rx - 30 * s, y - 78 * s, rx + 34 * s, y - 70 * s), fill=OUTLINE, width=w)
        return
    look_up = -10 * s if emotion == "thinking" else 0
    for x in (lx, rx):
        d.ellipse((x - 15 * s, y + look_up - 17 * s, x + 15 * s, y + look_up + 17 * s), fill=OUTLINE)
    if emotion == "angry":  # sourcils en V
        d.line((lx - 40 * s, y - 62 * s, lx + 32 * s, y - 28 * s), fill=OUTLINE, width=w + 2 * s)
        d.line((rx + 40 * s, y - 62 * s, rx - 32 * s, y - 28 * s), fill=OUTLINE, width=w + 2 * s)
    elif emotion == "sad":  # sourcils tombants
        d.line((lx - 36 * s, y - 28 * s, lx + 32 * s, y - 56 * s), fill=OUTLINE, width=w)
        d.line((rx + 36 * s, y - 28 * s, rx - 32 * s, y - 56 * s), fill=OUTLINE, width=w)
    elif emotion == "thinking":  # un sourcil levé
        d.line((lx - 34 * s, y - 52 * s, lx + 34 * s, y - 52 * s), fill=OUTLINE, width=w)
        d.line((rx - 34 * s, y - 78 * s, rx + 34 * s, y - 66 * s), fill=OUTLINE, width=w)


def _mouth(d, emotion: str, level: int, s: int):
    cx, y = 300 * s, 360 * s
    w = 11 * s
    if level > 0:  # bouche qui parle : ovale plus ou moins ouvert
        h = (14, 34, 62)[min(level, 3) - 1] * s
        half = (30, 36, 42)[min(level, 3) - 1] * s
        d.ellipse((cx - half, y - h // 2, cx + half, y + h // 2), fill=(70, 25, 25, 255), outline=OUTLINE, width=8 * s)
        if level == 3:
            d.ellipse((cx - 22 * s, y + 4 * s, cx + 22 * s, y + h // 2 - 2 * s), fill=(214, 96, 96, 255))
        return
    if emotion == "happy":
        d.pieslice((cx - 48 * s, y - 40 * s, cx + 48 * s, y + 46 * s), 0, 180, fill=(255, 255, 255, 255),
                   outline=OUTLINE, width=8 * s)
    elif emotion in ("sad", "angry"):
        d.arc((cx - 36 * s, y - 6 * s, cx + 36 * s, y + 40 * s), 200, 340, fill=OUTLINE, width=w)
    elif emotion == "surprised":
        d.ellipse((cx - 20 * s, y - 24 * s, cx + 20 * s, y + 28 * s), fill=(70, 25, 25, 255), outline=OUTLINE, width=8 * s)
    elif emotion == "thinking":
        d.line((cx - 20 * s, y + 4 * s, cx + 30 * s, y - 8 * s), fill=OUTLINE, width=w)
    else:
        d.line((cx - 30 * s, y, cx + 30 * s, y), fill=OUTLINE, width=w)


def _hat(d, design, s: int):
    col, cx, top = _rgba(design.hat_color), 300 * s, 70 * s
    if design.hat == "cap":
        d.pieslice((120 * s, 60 * s, 480 * s, 400 * s), 180, 360, fill=col, outline=OUTLINE, width=9 * s)
        d.ellipse((290 * s, 196 * s, 565 * s, 252 * s), fill=col, outline=OUTLINE, width=8 * s)
    elif design.hat == "beanie":
        d.pieslice((125 * s, 62 * s, 475 * s, 400 * s), 180, 360, fill=col, outline=OUTLINE, width=9 * s)
        d.rounded_rectangle((128 * s, 190 * s, 472 * s, 232 * s), 18 * s, fill=col, outline=OUTLINE, width=8 * s)
        d.ellipse((cx - 24 * s, top - 40 * s, cx + 24 * s, top + 8 * s), fill=col, outline=OUTLINE, width=7 * s)
    elif design.hat == "helmet":
        d.pieslice((112 * s, 52 * s, 488 * s, 420 * s), 180, 360, fill=col, outline=OUTLINE, width=9 * s)
        d.rectangle((110 * s, 214 * s, 490 * s, 236 * s), fill=col, outline=OUTLINE, width=7 * s)
        d.ellipse((cx - 16 * s, 118 * s, cx + 16 * s, 150 * s), fill=(240, 200, 80, 255), outline=OUTLINE, width=6 * s)
    elif design.hat == "hair":
        hair = _rgba(design.hair)
        pts = [(140, 200), (130, 120), (190, 150), (230, 60), (290, 130), (350, 50), (400, 140), (470, 110), (460, 200)]
        d.polygon([(x * s, y * s) for x, y in pts], fill=hair, outline=OUTLINE)
        d.line([(x * s, y * s) for x, y in pts] + [(140 * s, 200 * s)], fill=OUTLINE, width=8 * s, joint="curve")


def draw_puppet(design: PuppetDesign, emotion: str = "neutral", mouth: int = 0, blink: bool = False,
                arm_raise: float = 0.0, walk: float = 0.0, display_height: int = 820) -> Image.Image:
    """Dessine le personnage (RGBA, fond transparent) à la hauteur voulue.

    mouth : 0 (fermée) à 3 (grande ouverte) ; arm_raise : 0 (bras le long du corps) à 1 (bras levé) ;
    walk : -1 à 1, écarte les jambes (marche).
    """
    s = SS
    img = Image.new("RGBA", (CANVAS[0] * s, CANVAS[1] * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, line = _rgba(design.skin), 12 * s
    # jambes
    for hip, sign in ((262, -1), (338, 1)):
        foot_x = hip + sign * 14 + walk * sign * 34
        d.line((hip * s, 705 * s, foot_x * s, 925 * s), fill=OUTLINE, width=line)
        d.ellipse(((foot_x - 30) * s, 910 * s, (foot_x + 30) * s, 942 * s), fill=OUTLINE)
    # bras (gauche le long du corps, droit qui peut se lever)
    left_hand = (178 * s, 690 * s)
    d.line((205 * s, 480 * s, 165 * s, 600 * s, left_hand[0], left_hand[1]), fill=OUTLINE, width=line, joint="curve")
    ang = math.radians(20 + 130 * arm_raise ** 1.6)  # 20° : bras baissé ; ~63° : geste ; 150° : bras levé
    ex, ey = 395 * s + math.sin(ang) * 120 * s, 480 * s + math.cos(ang) * 120 * s
    hx, hy = 395 * s + math.sin(ang) * 215 * s, 480 * s + math.cos(ang) * 215 * s
    d.line((395 * s, 480 * s, ex, ey, hx, hy), fill=OUTLINE, width=line, joint="curve")
    for hand in (left_hand, (hx, hy)):
        d.ellipse((hand[0] - 20 * s, hand[1] - 20 * s, hand[0] + 20 * s, hand[1] + 20 * s), fill=skin, outline=OUTLINE, width=7 * s)
    # corps
    d.rounded_rectangle((190 * s, 430 * s, 410 * s, 720 * s), 46 * s, fill=_rgba(design.outfit), outline=OUTLINE, width=10 * s)
    if design.belt:
        d.rectangle((192 * s, 640 * s, 408 * s, 668 * s), fill=_rgba(design.pants), outline=OUTLINE, width=6 * s)
        d.rectangle((282 * s, 637 * s, 318 * s, 671 * s), fill=(240, 200, 80, 255), outline=OUTLINE, width=5 * s)
    d.line((235 * s, 440 * s, 365 * s, 585 * s), fill=OUTLINE, width=8 * s)  # bandoulière
    # tête
    d.ellipse((105 * s, 55 * s, 495 * s, 445 * s), fill=skin, outline=OUTLINE, width=11 * s)
    d.ellipse((276 * s, 292 * s, 324 * s, 330 * s), fill=_rgba("#e8b27f"), outline=None)  # nez
    face = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(face)
    _eyes_and_brows(fd, emotion, blink, s)
    _mouth(fd, emotion, mouth, s)
    box = (140 * s, 150 * s, 460 * s, 430 * s)
    region = face.crop(box)
    region = region.resize((round(region.width * FACE_SCALE), round(region.height * FACE_SCALE)), Image.LANCZOS)
    cx, cy = (box[0] + box[2]) // 2, 305 * s
    img.alpha_composite(region, (cx - region.width // 2, cy - region.height // 2))
    if design.hat != "none":
        _hat(d, design, s)
    bbox = img.getbbox()
    img = img.crop(bbox) if bbox else img
    ratio = display_height / img.height      # le personnage mesure exactement display_height de haut
    size = (max(1, round(img.width * ratio)), display_height)
    return img.resize(size, Image.LANCZOS)

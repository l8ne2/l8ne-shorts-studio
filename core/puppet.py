"""Personnage « marionnette » 2D dessiné par code.

Le personnage est composé de parties (tête, yeux, bouche, corps, bras, jambes) : on peut donc changer
d'expression, ouvrir la bouche au rythme de la voix, cligner des yeux, lever un bras...
Trois corps : « dressed » (habillé), « stick » (bonhomme bâton) et « cozy » (petit pull mignon).
Tout est dessiné avec Pillow : aucune image IA, aucun quota, rendu instantané.
"""
import json
import math
from dataclasses import asdict, dataclass, fields
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

DEFAULT_OUTLINE = "#261b16"
SS = 2                      # suréchantillonnage pour des contours lisses
OX, OY = 120, 40            # marge de dessin : laisse la place aux bras tendus (le dessin reste en coordonnées 600x1000)
CANVAS = (600 + 2 * OX, 1000 + OY)
CROP_TOP = 40               # zone conservée en hauteur : TOUJOURS la même, pour que le personnage ne « saute »
                            # pas quand un bras ou la tête bouge
HATS = ("none", "cap", "beanie", "helmet", "hair", "bowler", "tophat", "miner")
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
    moustache: bool = False
    glasses: bool = False

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
    elif design.hat == "bowler":
        d.pieslice((135 * s, 58 * s, 465 * s, 370 * s), 180, 360, fill=col, outline=ol, width=9 * s)
        d.ellipse((105 * s, 176 * s, 495 * s, 232 * s), fill=col, outline=ol, width=8 * s)
        d.rectangle((150 * s, 170 * s, 450 * s, 196 * s), fill=_rgba("#2a2a2a"), outline=ol, width=5 * s)
    elif design.hat == "tophat":
        d.rounded_rectangle((200 * s, 52 * s, 400 * s, 205 * s), 14 * s, fill=col, outline=ol, width=9 * s)
        d.ellipse((120 * s, 182 * s, 480 * s, 236 * s), fill=col, outline=ol, width=8 * s)
        d.rectangle((201 * s, 168 * s, 399 * s, 192 * s), fill=_rgba("#b8322f"), outline=ol, width=5 * s)
    elif design.hat == "miner":
        d.pieslice((112 * s, 52 * s, 488 * s, 420 * s), 180, 360, fill=col, outline=ol, width=9 * s)
        d.rectangle((104 * s, 212 * s, 496 * s, 238 * s), fill=col, outline=ol, width=7 * s)
        d.ellipse((cx - 30 * s, 112 * s, cx + 30 * s, 172 * s), fill=(255, 238, 150, 255), outline=ol, width=7 * s)
    elif design.hat == "hair":
        hair = _rgba(design.hair)
        pts = [(140, 200), (130, 120), (190, 150), (230, 60), (290, 130), (350, 50), (400, 140), (470, 110), (460, 200)]
        d.polygon([(x * s, y * s) for x, y in pts], fill=hair, outline=ol)
        d.line([(x * s, y * s) for x, y in pts] + [(140 * s, 200 * s)], fill=ol, width=8 * s, joint="curve")


class _Shift:
    """Décale tout ce qu'on dessine : le dessin est écrit en coordonnées « personnage » (600x1000), sans marge."""

    def __init__(self, draw, dx: int, dy: int):
        self._d, self._dx, self._dy = draw, dx, dy

    def _move(self, xy):
        if len(xy) and isinstance(xy[0], (tuple, list)):
            return [(x + self._dx, y + self._dy) for x, y in xy]
        return [v + (self._dx if i % 2 == 0 else self._dy) for i, v in enumerate(xy)]

    def __getattr__(self, name):
        fn = getattr(self._d, name)

        def call(xy, *args, **kwargs):
            return fn(self._move(xy), *args, **kwargs)
        return call


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


ARM_UPPER, ARM_FORE = 120, 100
SHOULDERS = {"dressed": ((205, 480), (395, 480)), "stick": ((300, 500), (300, 500)), "cozy": ((212, 500), (388, 500))}
REST_LEFT = {"dressed": [(205, 480), (165, 600), (178, 690)], "stick": [(300, 500), (245, 585), (215, 680)],
             "cozy": [(212, 500), (175, 600), (168, 670)]}


BODY_ARM = {"stick": (150, 135)}      # le bonhomme bâton a de plus longs bras (épaules au centre du corps)


def solve_arm(shoulder, target, lengths=(ARM_UPPER, ARM_FORE)):
    """Cinématique inverse à deux os : coude et main pour atteindre `target` (le coude reste vers le bas)."""
    upper, fore = lengths
    sx, sy = shoulder
    dx, dy = target[0] - sx, target[1] - sy
    dist = math.hypot(dx, dy)
    reach = upper + fore - 2
    if dist > reach:                      # cible trop loin : le bras se tend au maximum
        dx, dy, dist = dx * reach / dist, dy * reach / dist, reach
    if dist < 30.0:                       # cible (presque) sur l'épaule : la main se place juste en dessous
        dx, dy, dist = 0.0, 30.0, 30.0
    a = (upper ** 2 - fore ** 2 + dist ** 2) / (2 * dist)
    h = math.sqrt(max(upper ** 2 - a ** 2, 0.0))
    ux, uy = dx / dist, dy / dist
    px, py = sx + ux * a, sy + uy * a
    c1, c2 = (px - uy * h, py + ux * h), (px + uy * h, py - ux * h)
    elbow = c1 if c1[1] >= c2[1] else c2
    return elbow, (sx + dx, sy + dy)


def _right_arm(body, arm_raise, right_hand):
    sh = SHOULDERS[body][1]
    if right_hand is not None:
        elbow, hand = solve_arm(sh, right_hand, BODY_ARM.get(body, (ARM_UPPER, ARM_FORE)))
        return [sh, elbow, hand]
    a, e, h = _arm_points(arm_raise, 1, sh)
    return [a, e, h]


def _left_arm(body, left_hand):
    sh = SHOULDERS[body][0]
    if left_hand is not None:
        elbow, hand = solve_arm(sh, left_hand, BODY_ARM.get(body, (ARM_UPPER, ARM_FORE)))
        return [sh, elbow, hand]
    return list(REST_LEFT[body])


def _flat(points, s):
    return tuple(v * s for p in points for v in p)


def _legs_feet(walk, stride):
    """Décalage horizontal et hauteur de levée de chaque pied (gauche, droite) : jambes qui marchent."""
    left = (walk * -34 + stride * 45, max(0.0, stride) * 28)
    right = (walk * 34 - stride * 45, max(0.0, -stride) * 28)
    return left, right


def _legs_dressed(d, design, s, ol, k, walk, stride):
    line = round(12 * k) * s
    (lx, ll), (rx, rl) = _legs_feet(walk, stride)
    for hip, sign, shift, lift in ((262, -1, lx, ll), (338, 1, rx, rl)):
        foot_x = hip + sign * 14 + shift
        d.line((hip * s, 705 * s, foot_x * s, (925 - lift) * s), fill=ol, width=line)
        d.ellipse(((foot_x - 30) * s, (910 - lift) * s, (foot_x + 30) * s, (942 - lift) * s), fill=ol)


def _arms_dressed(d, design, s, ol, k, left_pts, right_pts, skin):
    line = round(12 * k) * s
    for pts in (left_pts, right_pts):
        d.line(_flat(pts, s), fill=ol, width=line, joint="curve")
        hx, hy = pts[-1]
        d.ellipse(((hx - 20) * s, (hy - 20) * s, (hx + 20) * s, (hy + 20) * s), fill=skin, outline=ol, width=7 * s)


def _torso_dressed(d, design, s, ol, k):
    d.rounded_rectangle((190 * s, 430 * s, 410 * s, 720 * s), 46 * s, fill=_rgba(design.outfit), outline=ol, width=round(10 * k) * s)
    if design.belt:
        d.rectangle((192 * s, 640 * s, 408 * s, 668 * s), fill=_rgba(design.pants), outline=ol, width=6 * s)
        d.rectangle((282 * s, 637 * s, 318 * s, 671 * s), fill=(240, 200, 80, 255), outline=ol, width=5 * s)
    d.line((235 * s, 440 * s, 365 * s, 585 * s), fill=ol, width=8 * s)  # bandoulière


def _legs_stick(d, design, s, ol, k, walk, stride):
    line = round(13 * k) * s
    (lx, ll), (rx, rl) = _legs_feet(walk, stride)
    for sign, shift, lift in ((-1, lx, ll), (1, rx, rl)):
        foot_x = 300 + sign * 55 + shift
        d.line((300 * s, 700 * s, (300 + sign * 40 + shift / 2) * s, (810 - lift / 2) * s, foot_x * s, (925 - lift) * s),
               fill=ol, width=line, joint="curve")
        d.ellipse(((foot_x - 26) * s, (912 - lift) * s, (foot_x + 26) * s, (940 - lift) * s), fill=ol)


def _arms_stick(d, design, s, ol, k, left_pts, right_pts, skin):
    line = round(13 * k) * s
    for pts in (left_pts, right_pts):
        d.line(_flat(pts, s), fill=ol, width=line, joint="curve")
        hx, hy = pts[-1]
        d.ellipse(((hx - 21) * s, (hy - 21) * s, (hx + 21) * s, (hy + 21) * s), fill=ol)  # petites mains pleines


def _torso_stick(d, design, s, ol, k):
    d.line((300 * s, 430 * s, 300 * s, 705 * s), fill=ol, width=round(13 * k) * s)


def _legs_cozy(d, design, s, ol, k, walk, stride):
    out, pants = round(9 * k) * s, _rgba(design.pants)
    (lx, ll), (rx, rl) = _legs_feet(walk, stride)
    for cx_, sign, shift, lift in ((262, -1, lx, ll), (338, 1, rx, rl)):
        foot = cx_ + sign * 8 + shift
        d.rounded_rectangle(((foot - 30) * s, 650 * s, (foot + 30) * s, (905 - lift) * s), 28 * s, fill=pants, outline=ol, width=out)
        d.ellipse(((foot - 38) * s, (888 - lift) * s, (foot + 38) * s, (940 - lift) * s), fill=_rgba("#8a6f58"), outline=ol, width=out)


def _arms_cozy(d, design, s, ol, k, left_pts, right_pts, skin):
    out, sweater = round(9 * k) * s, _rgba(design.outfit)
    for pts in (left_pts, right_pts):
        d.line(_flat(pts, s), fill=ol, width=round(46 * k) * s, joint="curve")
        d.line(_flat(pts, s), fill=sweater, width=round(46 * k) * s - 2 * out, joint="curve")
        hx, hy = pts[-1]
        d.ellipse(((hx - 22) * s, (hy - 22) * s, (hx + 22) * s, (hy + 22) * s), fill=skin, outline=ol, width=out)


def _torso_cozy(d, design, s, ol, k):
    out = round(9 * k) * s
    d.rounded_rectangle((195 * s, 435 * s, 405 * s, 700 * s), 78 * s, fill=_rgba(design.outfit), outline=ol, width=out)
    d.line((215 * s, 668 * s, 385 * s, 668 * s), fill=_rgba(design.pants, 90), width=5 * s)  # bord du pull


BODY_PARTS = {  # (jambes, bras, torse)
    "dressed": (_legs_dressed, _arms_dressed, _torso_dressed),
    "stick": (_legs_stick, _arms_stick, _torso_stick),
    "cozy": (_legs_cozy, _arms_cozy, _torso_cozy),
}


def _draw_prop(d, name: str, hand, s: int, ol, skin) -> None:
    """Objet tenu à la main (téléphone, argent, tasse, journal, loupe), puis la main par-dessus."""
    hx, hy = hand
    if name == "phone":
        d.rounded_rectangle(((hx - 30) * s, (hy - 92) * s, (hx + 30) * s, (hy + 12) * s), 9 * s, fill=(34, 38, 52, 255), outline=ol, width=5 * s)
        d.rounded_rectangle(((hx - 23) * s, (hy - 82) * s, (hx + 23) * s, (hy - 8) * s), 5 * s, fill=(150, 205, 255, 255))
    elif name == "money":
        for off in (14, 0):
            d.rectangle(((hx - 50 + off) * s, (hy - 52 + off) * s, (hx + 40 + off) * s, (hy + off) * s), fill=(120, 195, 120, 255), outline=ol, width=5 * s)
        d.ellipse(((hx - 16) * s, (hy - 38) * s, (hx + 16) * s, (hy - 8) * s), fill=(185, 232, 185, 255), outline=ol, width=4 * s)
    elif name == "cup":
        d.rounded_rectangle(((hx - 26) * s, (hy - 54) * s, (hx + 26) * s, (hy + 8) * s), 8 * s, fill=(250, 250, 250, 255), outline=ol, width=5 * s)
        d.arc(((hx + 14) * s, (hy - 42) * s, (hx + 52) * s, (hy - 4) * s), 270, 90, fill=ol, width=5 * s)
    elif name == "newspaper":
        d.rectangle(((hx - 58) * s, (hy - 100) * s, (hx + 58) * s, (hy + 14) * s), fill=(245, 240, 224, 255), outline=ol, width=5 * s)
        for i in range(5):
            d.line(((hx - 44) * s, (hy - 80 + i * 20) * s, (hx + 44) * s, (hy - 80 + i * 20) * s), fill=(150, 145, 130, 255), width=4 * s)
    elif name == "magnifier":
        d.ellipse(((hx - 34) * s, (hy - 100) * s, (hx + 34) * s, (hy - 32) * s), fill=(210, 235, 250, 150), outline=ol, width=7 * s)
        d.line((hx * s, (hy - 32) * s, hx * s, (hy + 10) * s), fill=ol, width=9 * s)
    d.ellipse(((hx - 20) * s, (hy - 20) * s, (hx + 20) * s, (hy + 20) * s), fill=skin, outline=ol, width=6 * s)


PROPS = ("phone", "money", "cup", "newspaper", "magnifier")


RX0, RY0, RX1, RY1 = 100, 40, 800, 560        # zone de la tête (coordonnées du calque) : seule elle est retravaillée


def _region_shift():
    return (OX - RX0) * SS, (OY - RY0) * SS


def _shade_head(img: Image.Image, skin, s: int, sx: int, sy: int) -> None:
    """Ombre douce en croissant en bas à droite + reflet en haut à gauche (lumière venant du haut-gauche)."""
    x0, y0, x1, y1 = HEAD_BOX
    inset = 14
    box = ((x0 + inset) * s + sx, (y0 + inset) * s + sy, (x1 - inset) * s + sx, (y1 - inset) * s + sy)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    off = Image.new("L", img.size, 0)
    ImageDraw.Draw(off).ellipse((box[0] - 55 * s, box[1] - 55 * s, box[2] - 55 * s, box[3] - 55 * s), fill=255)
    crescent = ImageChops.subtract(mask, off).filter(ImageFilter.GaussianBlur(10 * s))
    shade = Image.new("RGBA", img.size, _darker(skin, 0.78) + (0,))
    shade.putalpha(crescent.point(lambda v: v * 95 // 255))
    img.alpha_composite(shade)
    glow = Image.new("RGBA", img.size, (255, 255, 255, 0))  # base blanche : le flou ne crée pas de halo gris
    ImageDraw.Draw(glow).ellipse((165 * s + sx, 105 * s + sy, 250 * s + sx, 165 * s + sy), fill=(255, 255, 255, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12 * s)))


@lru_cache(maxsize=32)
def _head_base(design_json: str) -> Image.Image:
    """Partie de la tête qui ne dépend que du personnage (crâne, ombrage, joues, nez) : dessinée une seule fois."""
    design = PuppetDesign.from_json(design_json)
    s, k = SS, design.line_scale
    sx, sy = _region_shift()
    img = Image.new("RGBA", ((RX1 - RX0) * s, (RY1 - RY0) * s), (0, 0, 0, 0))
    skin, ol = _rgba(design.skin), _rgba(design.outline)
    hd = _Shift(ImageDraw.Draw(img), sx, sy)
    hd.ellipse(tuple(v * s for v in HEAD_BOX), fill=skin, outline=ol, width=round(11 * k) * s)
    if design.shading:
        _shade_head(img, skin, s, sx, sy)
    if design.blush:
        cheeks = Image.new("RGBA", img.size, (240, 130, 130, 0))
        cd = _Shift(ImageDraw.Draw(cheeks), sx, sy)
        for cx_ in (172, 428):
            cd.ellipse(((cx_ - 34) * s, 322 * s, (cx_ + 34) * s, 358 * s), fill=(240, 130, 130, 120))
        img.alpha_composite(cheeks.filter(ImageFilter.GaussianBlur(5 * s)))
    if design.body != "stick":  # petit nez (le bonhomme bâton classique n'en a pas)
        hd = _Shift(ImageDraw.Draw(img), sx, sy)
        hd.ellipse((276 * s, 292 * s, 324 * s, 330 * s), fill=_rgba("#e8b27f") if design.body == "dressed" else _darker(skin, 0.92) + (255,))
    return img


def _head_region(design, emotion, mouth, blink) -> Image.Image:
    """Tête complète (visage, moustache, lunettes, chapeau) dans la zone de la tête."""
    s, ol, k = SS, _rgba(design.outline), design.line_scale
    sx, sy = _region_shift()
    head = _head_base(design.to_json()).copy()
    fw, fh = 320 * s, 280 * s
    face = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    fd = _Shift(ImageDraw.Draw(face), -140 * s, -150 * s)
    _eyes_and_brows(fd, emotion, blink, s, ol, k)
    _mouth(fd, emotion, mouth, s, ol, k)
    region = face.resize((round(fw * FACE_SCALE), round(fh * FACE_SCALE)), Image.BICUBIC)
    cx, cy = 300 * s + sx, 305 * s + sy
    head.alpha_composite(region, (cx - region.width // 2, cy - region.height // 2))
    hd = _Shift(ImageDraw.Draw(head), sx, sy)
    if design.moustache:
        mc = _rgba(design.hair)
        hd.ellipse((248 * s, 326 * s, 304 * s, 352 * s), fill=mc, outline=ol, width=4 * s)
        hd.ellipse((296 * s, 326 * s, 352 * s, 352 * s), fill=mc, outline=ol, width=4 * s)
        hd.arc((232 * s, 322 * s, 272 * s, 356 * s), 100, 200, fill=ol, width=5 * s)
        hd.arc((328 * s, 322 * s, 368 * s, 356 * s), 340, 80, fill=ol, width=5 * s)
    if design.glasses:
        for gx in (195, 405):
            hd.ellipse(((gx - 50) * s, 208 * s, (gx + 50) * s, 306 * s), outline=ol, width=6 * s)
        hd.line((245 * s, 252 * s, 355 * s, 252 * s), fill=ol, width=6 * s)
    if design.hat != "none":
        _hat(hd, design, s, ol)
    return head


def _finish(img: Image.Image, display_height: int) -> Image.Image:
    """Zone conservée toujours identique (le personnage ne « saute » pas), mise à l'échelle voulue."""
    img = img.crop((0, CROP_TOP * SS, CANVAS[0] * SS, CANVAS[1] * SS))
    ratio = display_height / img.height
    return img.resize((max(1, round(img.width * ratio)), display_height), Image.BOX)


def draw_body_layers(design: PuppetDesign, arm_raise: float = 0.0, walk: float = 0.0, right_hand=None,
                     left_hand=None, stride: float = 0.0, prop: str = None, front_arms: bool = False,
                     display_height: int = 820):
    """Corps du personnage en deux calques de même taille : (derrière, devant).

    « derrière » : jambes, torse et bras (sauf si front_arms) ; « devant » : bras devant la tête et objet tenu
    (None s'il n'y a rien à dessiner devant). La tête se dessine à part (draw_head_layer) : on peut ainsi
    réutiliser les calques déjà dessinés et ne recalculer que ce qui change.
    """
    s = SS
    k = design.line_scale
    ol = _rgba(design.outline)
    skin = _rgba(design.skin)
    body = design.body if design.body in BODY_PARTS else "dressed"
    legs_fn, arms_fn, torso_fn = BODY_PARTS[body]
    left_pts, right_pts = _left_arm(body, left_hand), _right_arm(body, arm_raise, right_hand)

    back = Image.new("RGBA", (CANVAS[0] * s, CANVAS[1] * s), (0, 0, 0, 0))
    d = _Shift(ImageDraw.Draw(back), OX * s, OY * s)
    legs_fn(d, design, s, ol, k, walk, stride)
    if not front_arms:
        arms_fn(d, design, s, ol, k, left_pts, right_pts, skin)
    torso_fn(d, design, s, ol, k)

    front = None
    if front_arms or prop in PROPS:
        front = Image.new("RGBA", back.size, (0, 0, 0, 0))
        fd = _Shift(ImageDraw.Draw(front), OX * s, OY * s)
        if front_arms:
            arms_fn(fd, design, s, ol, k, left_pts, right_pts, skin)
        if prop in PROPS:
            _draw_prop(fd, prop, right_pts[-1], s, ol, ol if body == "stick" else skin)
    return _finish(back, display_height), (_finish(front, display_height) if front is not None else None)


def draw_head_layer(design: PuppetDesign, emotion: str = "neutral", mouth: int = 0, blink: bool = False,
                    head_tilt: float = 0.0, head_dy: float = 0.0, display_height: int = 820) -> Image.Image:
    """Tête seule (même taille et même repère que les calques du corps), éventuellement inclinée ou baissée."""
    ratio = display_height / (CANVAS[1] - CROP_TOP)          # pixels d'affichage par unité du dessin
    head = _head_region(design, emotion, mouth, blink)
    # on réduit d'abord (rapide, le dessin est suréchantillonné), puis on incline la petite image
    region = head.resize((round((RX1 - RX0) * ratio), round((RY1 - RY0) * ratio)), Image.BOX)
    if head_tilt:
        region = region.rotate(-head_tilt, resample=Image.BICUBIC,
                               center=((300 + OX - RX0) * ratio, (445 + OY - RY0) * ratio))
    if head_dy:
        region = region.transform(region.size, Image.AFFINE, (1, 0, 0, 0, 1, -head_dy * ratio), resample=Image.BICUBIC)
    layer = Image.new("RGBA", (round(CANVAS[0] * ratio), display_height), (0, 0, 0, 0))
    layer.alpha_composite(region, (round(RX0 * ratio), round((RY0 - CROP_TOP) * ratio)))
    return layer


def compose_puppet(back: Image.Image, head: Image.Image, front: Image.Image = None) -> Image.Image:
    img = back.copy()
    img.alpha_composite(head)
    if front is not None:
        img.alpha_composite(front)
    return img


def draw_puppet(design: PuppetDesign, emotion: str = "neutral", mouth: int = 0, blink: bool = False,
                arm_raise: float = 0.0, walk: float = 0.0, display_height: int = 820,
                right_hand=None, left_hand=None, head_tilt: float = 0.0, head_dy: float = 0.0,
                stride: float = 0.0, prop: str = None, front_arms: bool = False) -> Image.Image:
    """Dessine le personnage complet (RGBA, fond transparent). La taille de l'image est toujours la même.

    mouth : 0 (fermée) à 3 (grande ouverte) ; arm_raise : 0 (bras pendant) à 1 (bras levé) ;
    right_hand / left_hand : position cible (x, y) de la main, en coordonnées du dessin 600x1000
    (cinématique inverse : le coude suit) ; head_tilt : inclinaison de la tête en degrés (+ = vers la droite) ;
    head_dy : la tête descend de n pixels (acquiescer) ; walk / stride : marche ; prop : objet tenu à la main
    droite ; front_arms : bras dessinés devant la tête (main devant le visage...).
    """
    back, front = draw_body_layers(design, arm_raise, walk, right_hand, left_hand, stride, prop, front_arms,
                                   display_height)
    head = draw_head_layer(design, emotion, mouth, blink, head_tilt, head_dy, display_height)
    return compose_puppet(back, head, front)


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
        "bowler": f"a {color_name(design.hat_color)} bowler hat", "tophat": f"a {color_name(design.hat_color)} top hat",
        "miner": f"a {color_name(design.hat_color)} miner helmet with a lamp",
    }
    extras = (", a big mustache" if design.moustache else "") + (", round glasses" if design.glasses else "")
    head = (f"a cute cartoon stickman character with a big perfectly round {color_name(design.skin)} head and "
            f"thick {color_name(design.outline)} outlines, {hats.get(design.hat, 'no hat')}{extras}")
    if design.body == "stick":
        return head + ", thin stick-figure body with simple line arms and legs, no clothes, simple dot eyes"
    if design.body == "cozy":
        return (head + f", wearing a soft {color_name(design.outfit)} sweater and {color_name(design.pants)} pants, "
                "short simple limbs, simple dot eyes, gentle friendly look")
    return (head + f", wearing a {color_name(design.outfit)} shirt, thin black stick arms and legs, simple dot eyes")

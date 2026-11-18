"""Jeu d'acteur : décide, à partir de la voix, quand un personnage fait un geste, lequel, quand il acquiesce,
saute, tremble ou réagit. Tout est calculé à l'avance et de façon déterministe (même résultat à chaque rendu).
"""
import math
from dataclasses import dataclass, field

import numpy as np

from core.puppet import BODY_ARM, REST_LEFT, SHOULDERS, _right_arm

FPS = 30

INTENSITIES = {
    "calm": {"label": "Calme", "gap": 2.4, "dur": 1.1, "nod": False, "reactions": False, "jump": False, "shake": False, "tilt": 2},
    "normal": {"label": "Naturel", "gap": 1.5, "dur": 0.9, "nod": True, "reactions": False, "jump": False, "shake": False, "tilt": 3},
    "expressive": {"label": "Expressif", "gap": 1.0, "dur": 0.85, "nod": True, "reactions": True, "jump": True, "shake": False, "tilt": 4},
    "comic": {"label": "Comique (exagéré)", "gap": 0.8, "dur": 0.75, "nod": True, "reactions": True, "jump": True, "shake": True, "tilt": 5},
}
DEFAULT_INTENSITY = "normal"

# Positions cibles de la main droite (coordonnées du dessin 600x1000) ; la gauche est le miroir (600 - x).
GESTURES = {
    "explain": {"right": (480, 500)},
    "point": {"right": (560, 420)},
    "wave": {"right": (530, 330)},
    "open_arms": {"right": (545, 470), "left": (55, 470)},
    "shrug": {"right": (505, 470), "left": (95, 470)},
    "cheer": {"right": (545, 240), "left": (55, 240)},
    "head_hold": {"right": (470, 150), "left": (130, 150)},
    "think": {"right": (340, 420), "front": True},
    "facepalm": {"right": (330, 310), "front": True},
}
EMOTION_GESTURES = {
    "neutral": ["explain", "point", "open_arms"],
    "happy": ["wave", "open_arms", "cheer"],
    "surprised": ["cheer", "head_hold", "open_arms"],
    "angry": ["point", "explain", "point"],
    "sad": ["shrug", "facepalm"],
    "thinking": ["think", "shrug", "explain"],
    "tired": ["facepalm", "shrug"],
    "relaxed": ["open_arms", "explain"],
}
GESTURE_EXPRESSION = {"cheer": "happy", "head_hold": "surprised", "think": "thinking", "shrug": "sad",
                      "facepalm": "tired", "wave": "happy", "open_arms": "happy"}
GESTURE_HEAD = {"think": (6, 0), "wave": (-5, 0), "facepalm": (0, 16), "shrug": (-4, 4), "cheer": (0, -6)}
HEAD_BASE = {"thinking": (8, 0), "sad": (-4, 10), "tired": (-5, 12), "angry": (0, 6), "surprised": (0, -5),
             "relaxed": (-3, 0)}
HOLD = {"phone": ((385, 430), True), "money": ((470, 560), False), "cup": ((455, 540), False),
        "newspaper": ((445, 490), False), "magnifier": ((455, 445), False)}
ENTRANCES = ("pop", "walk_left", "pop", "walk_right", "drop")
REACTIONS = ("surprised", "thinking", "happy")


def smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out_back(x: float) -> float:
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def ease_out_bounce(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    n1, d1 = 7.5625, 2.75
    if x < 1 / d1:
        return n1 * x * x
    if x < 2 / d1:
        x -= 1.5 / d1
        return n1 * x * x + 0.75
    if x < 2.5 / d1:
        x -= 2.25 / d1
        return n1 * x * x + 0.9375
    x -= 2.625 / d1
    return n1 * x * x + 0.984375


def entrance(mode: str, t: float) -> dict:
    """Entrée du personnage dans la scène : échelle, décalage et pas de marche à l'instant t (secondes)."""
    out = {"scale": 1.0, "x_off": 0.0, "y_off": 0.0, "stride": 0.0}
    if mode == "pop":
        out["scale"] = max(ease_out_back(min(t / 0.35, 1.0)), 0.01)
    elif mode in ("walk_left", "walk_right") and t < 0.9:
        sign = -1 if mode == "walk_left" else 1
        out["x_off"] = sign * ((1 - t / 0.9) ** 3) * 700          # arrive en ralentissant
        out["stride"] = math.sin(2 * math.pi * 2.4 * t) * 0.9
    elif mode == "drop" and t < 0.7:
        out["y_off"] = -900 * (1 - ease_out_bounce(t / 0.7))
    return out


def entrance_for(index: int, intensity: str) -> str:
    return "pop" if intensity == "calm" else ENTRANCES[index % len(ENTRANCES)]


@dataclass
class Event:
    t0: float
    dur: float
    gesture: str


@dataclass
class ActorPlan:
    events: list
    emotion: str = "neutral"
    intensity: str = DEFAULT_INTENSITY
    body: str = "dressed"
    prop: str = None
    phase: float = 0.0
    reactions: list = field(default_factory=list)   # [(début, fin, émotion)] : réactions de celui qui écoute


def _in_ranges(t: float, ranges) -> bool:
    return ranges is None or any(a <= t < b for a, b in ranges)


def build_events(envelope, t0: float, t1: float, active_ranges=None, emotion: str = "neutral",
                 intensity: str = DEFAULT_INTENSITY, seed: int = 0, has_prop: bool = False, fps: int = FPS) -> list:
    """Gestes d'un personnage entre t0 et t1 (secondes de l'audio complet).

    Un geste part sur chaque temps fort de la voix (au moins `gap` secondes d'écart) ; si la voix reste
    longtemps sans temps fort, on en ajoute un pour que le personnage ne reste pas figé en parlant.
    """
    cfg = INTENSITIES.get(intensity, INTENSITIES[DEFAULT_INTENSITY])
    env = np.asarray(envelope, dtype="float32")
    if env.size == 0:
        return []
    w = max(1, int(0.25 * fps))
    sm = np.convolve(env, np.ones(w) / w, mode="same")
    choices = ["explain", "wave"] if has_prop else EMOTION_GESTURES.get(emotion, EMOTION_GESTURES["neutral"])
    events, last, n = [], t0 - cfg["gap"] + 0.4, 0
    for i in range(max(int(t0 * fps), 0), min(int(t1 * fps), len(sm))):
        t = i / fps
        if t < t0 + 0.4 or t > t1 - 0.45 or not _in_ranges(t, active_ranges):
            continue
        peak = sm[i] >= 0.55 and sm[i] >= sm[max(0, i - w): i + w + 1].max() - 1e-6
        idle = (t - last) >= cfg["gap"] * 1.9 and sm[i] > 0.3
        if (peak and t - last >= cfg["gap"]) or idle:
            events.append(Event(t, cfg["dur"], choices[(seed + n) % len(choices)]))
            last, n = t, n + 1
    return events


def _quant(v: float, step: float) -> float:
    return round(v / step) * step


def _mirror(pt):
    return (600 - pt[0], pt[1])


def pose_state(plan: ActorPlan, gt: float, t_scene: float, is_active: bool = True) -> dict:
    """État du personnage à l'instant gt (audio complet) : expression, mains, tête, décalages."""
    cfg = INTENSITIES.get(plan.intensity, INTENSITIES[DEFAULT_INTENSITY])
    state = {"emotion": plan.emotion, "right_hand": None, "left_hand": None, "front_arms": False,
             "head_tilt": 0, "head_dy": 0, "x_off": 0.0, "y_off": 0.0, "prop": plan.prop, "gesture": None}
    base_tilt, base_dy = HEAD_BASE.get(plan.emotion, (0, 0))
    event = next((e for e in plan.events if e.t0 <= gt < e.t0 + e.dur), None)
    stick = plan.body == "stick"
    lengths = BODY_ARM.get(plan.body)

    # objet tenu : la main droite le garde pendant toute la scène
    hold_right, hold_front = None, False
    if plan.prop in HOLD:
        hold_right, hold_front = HOLD[plan.prop]
        state["right_hand"], state["front_arms"] = hold_right, hold_front

    u = p = 0.0
    if event:
        u = (gt - event.t0) / event.dur
        p = smoothstep(u / 0.25) if u < 0.25 else (1.0 if u < 0.65 else smoothstep((1 - u) / 0.35))
        q = round(p * 4) / 4
        spec = GESTURES[event.gesture]
        state["gesture"] = event.gesture
        if q > 0:
            right_rest = _right_arm(plan.body, 0, None)[-1]
            left_rest = REST_LEFT[plan.body][-1]

            def target(pt):
                if stick:  # épaules au centre : on écarte les cibles pour que les mains sortent de la tête
                    pt = (300 + (pt[0] - 300) * 1.2, pt[1])
                return pt

            def lerp(rest, goal):
                return (round(rest[0] + (goal[0] - rest[0]) * q), round(rest[1] + (goal[1] - rest[1]) * q))

            right_goal, left_goal = spec.get("right"), spec.get("left")
            if plan.prop in HOLD:                      # la main droite tient l'objet : on gesticule de la gauche
                left_goal, right_goal = _mirror(right_goal), None
            if right_goal:
                state["right_hand"] = lerp(right_rest, target(right_goal))
            if left_goal:
                state["left_hand"] = lerp(left_rest, target(_mirror(left_goal) if "left" not in spec else left_goal))
            state["front_arms"] = state["front_arms"] or bool(spec.get("front"))
        gt_tilt, gt_dy = GESTURE_HEAD.get(event.gesture, (0, 0))
        base_tilt += gt_tilt * p
        base_dy += gt_dy * p
        if cfg["nod"] and is_active and (gt - event.t0) < 0.18:   # petit hochement de tête sur le temps fort
            base_dy += 12 * smoothstep(1 - abs((gt - event.t0) - 0.09) / 0.09)
        if cfg["reactions"] and plan.emotion in ("neutral", "relaxed") and event.gesture in GESTURE_EXPRESSION:
            state["emotion"] = GESTURE_EXPRESSION[event.gesture]
        if cfg["jump"] and u < 0.4 and (event.gesture in ("cheer", "head_hold") or plan.emotion == "surprised"):
            state["y_off"] = -45 * math.sin(math.pi * u / 0.4)
        if cfg["shake"] and u < 0.35 and (plan.emotion == "angry" or event.gesture == "point"):
            state["x_off"] = 10 * math.sin(gt * 80) * (1 - u / 0.35)

    for a, b, emo in plan.reactions:                      # réaction de celui qui écoute
        if a <= gt < b:
            state["emotion"] = emo
    sway = cfg["tilt"] * math.sin(2 * math.pi * 0.4 * gt + plan.phase)
    state["head_tilt"] = int(max(-15, min(15, _quant(base_tilt + sway, 3))))
    state["head_dy"] = int(max(-12, min(18, _quant(base_dy, 6))))
    return state


def reaction_windows(timeline: list, speaker: int, intensity: str, length: float = 0.7) -> list:
    """Réactions du personnage `speaker` quand l'autre vient de finir de parler (expressif et comique seulement)."""
    if not INTENSITIES.get(intensity, {}).get("reactions"):
        return []
    out = []
    for n, seg in enumerate(timeline or []):
        if seg["speaker"] != speaker and n + 1 < len(timeline) and timeline[n + 1]["speaker"] == speaker:
            out.append((seg["end"] - 0.25, seg["end"] - 0.25 + length, REACTIONS[n % len(REACTIONS)]))
    return out

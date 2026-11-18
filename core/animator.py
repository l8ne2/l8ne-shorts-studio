"""Animation d'une scène : décor avec mouvement de caméra + personnage(s) qui jouent la scène.

Les images sont calculées par Pillow puis envoyées à FFmpeg (aucun fichier intermédiaire).
Personnage « puppet » : bouche synchronisée sur la voix, clignements, gestes des deux bras, hochements de tête,
expressions qui réagissent, entrées en marchant / en tombant (voir core/acting.py).
Personnage « sprite » (image IA découpée) : rebond et écrasement au rythme de la voix.
"""
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from core import acting
from core.acting import ActorPlan, ease_out_back, entrance, entrance_for, pose_state, reaction_windows
from core.dialogue import speaker_at
from core.puppet import PuppetDesign, compose_puppet, draw_body_layers, draw_head_layer

W, H, FPS = 1080, 1920, 30
MOTIONS = ("zoom_in", "pan_right", "zoom_out", "pan_left")
IMPACT_EMOTIONS = ("angry", "surprised")
DIALOGUE_HEIGHT = 820
DIALOGUE_X = (300, 780)      # position horizontale des deux personnages du dialogue


class AnimationError(Exception):
    """Erreur lors du rendu d'une scène animée."""


@dataclass
class SceneSpec:
    background: str
    duration: float
    start_time: float = 0.0          # position de la scène dans l'audio complet
    index: int = 0
    emotion: str = "neutral"
    kind: str = "puppet"             # "puppet" | "sprite"
    design: dict = field(default_factory=dict)
    sprite: str = None
    char_height: int = 1000
    bottom_margin: int = 300
    intensity: str = acting.DEFAULT_INTENSITY    # « jeu d'acteur » : calm | normal | expressive | comic
    prop: str = None                 # objet tenu (téléphone, argent, tasse, journal, loupe)
    entrance: str = None             # pop | walk_left | walk_right | drop (sinon : selon la scène et l'intensité)
    # Dialogue : deux personnages [{"design": {...}, "emotion": "happy"}, ...] et qui parle quand
    # ([{"speaker": 0, "start": 0.0, "end": 2.1}, ...], en secondes de l'audio complet)
    characters: list = None
    timeline: list = None


def camera_box(index: int, t: float, duration: float, emotion: str):
    """Fenêtre de recadrage (x0, y0, x1, y1) du décor : zoom/déplacement + secousse d'impact."""
    p = t / max(duration, 0.001)
    motion = MOTIONS[index % len(MOTIONS)]
    zoom = {"zoom_in": 1.0 + 0.12 * p, "zoom_out": 1.12 - 0.12 * p}.get(motion, 1.12)
    w, h = W / zoom, H / zoom
    cx = W / 2
    if motion == "pan_right":
        cx = w / 2 + (W - w) * p
    elif motion == "pan_left":
        cx = w / 2 + (W - w) * (1 - p)
    cy = H / 2
    if emotion in IMPACT_EMOTIONS and t < 0.3:  # petite secousse au début de la scène
        k = 1 - t / 0.3
        cx += 16 * math.sin(t * 70) * k
        cy += 12 * math.cos(t * 85) * k
    x0 = min(max(cx - w / 2, 0), W - w)
    y0 = min(max(cy - h / 2, 0), H - h)
    return (x0, y0, x0 + w, y0 + h)


def _shadow(width: int) -> Image.Image:
    sh = Image.new("RGBA", (width, 60), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(sh).ellipse((0, 0, width - 1, 59), fill=(0, 0, 0, 70))
    return sh


class _Performer:
    """Un personnage dans une scène : son plan de jeu et les calques déjà dessinés (corps et tête séparés)."""

    def __init__(self, character: dict, plan: ActorPlan, mirrored: bool, height: int, kind: str = "puppet",
                 sprite: str = None):
        self.design = PuppetDesign(**{k: v for k, v in (character.get("design") or {}).items()
                                      if k in PuppetDesign.__dataclass_fields__})
        self.plan, self.mirrored, self.height, self.kind = plan, mirrored, height, kind
        self.body_cache, self.head_cache = {}, {}
        self.sprite_img = None
        if kind == "sprite" and sprite:
            img = Image.open(sprite).convert("RGBA")
            ratio = height / img.height
            self.sprite_img = img.resize((max(1, round(img.width * ratio)), height), Image.LANCZOS)

    def _flip(self, img):
        return ImageOps.mirror(img) if (self.mirrored and img is not None) else img

    def image(self, st: dict, mouth: int, blink: bool, stride: float):
        if self.sprite_img is not None:
            return self.sprite_img
        stride_q = round(stride * 2) / 2
        body_key = (st["right_hand"], st["left_hand"], st["front_arms"], stride_q, st["prop"])
        if body_key not in self.body_cache:
            back, front = draw_body_layers(self.design, 0.0, 0.0, st["right_hand"], st["left_hand"], stride_q,
                                           st["prop"], st["front_arms"], self.height)
            self.body_cache[body_key] = (self._flip(back), self._flip(front))
        head_key = (st["emotion"], mouth, blink, st["head_tilt"], st["head_dy"])
        if head_key not in self.head_cache:
            head = draw_head_layer(self.design, st["emotion"], mouth, blink, st["head_tilt"], st["head_dy"], self.height)
            self.head_cache[head_key] = self._flip(head)
        back, front = self.body_cache[body_key]
        return compose_puppet(back, self.head_cache[head_key], front)


def _build_performers(spec: SceneSpec, envelope, kind_default: str = "puppet"):
    """Plans de jeu des personnages de la scène (un seul, ou deux en dialogue)."""
    t0, t1 = spec.start_time, spec.start_time + spec.duration
    if spec.characters:
        chars = spec.characters[:2]
        performers = []
        for i, c in enumerate(chars):
            ranges = [(seg["start"], seg["end"]) for seg in (spec.timeline or []) if seg["speaker"] == i]
            design = PuppetDesign(**{k: v for k, v in (c.get("design") or {}).items() if k in PuppetDesign.__dataclass_fields__})
            emotion = c.get("emotion", "neutral")
            plan = ActorPlan(
                events=acting.build_events(envelope, t0, t1, ranges, emotion, spec.intensity, seed=spec.index + i),
                emotion=emotion, intensity=spec.intensity, body=design.body, phase=i * 1.7 + spec.index,
                reactions=reaction_windows(spec.timeline, i, spec.intensity))
            performers.append(_Performer(c, plan, mirrored=(i == 1), height=DIALOGUE_HEIGHT))
        return performers
    design = PuppetDesign(**{k: v for k, v in (spec.design or {}).items() if k in PuppetDesign.__dataclass_fields__})
    plan = ActorPlan(
        events=acting.build_events(envelope, t0, t1, None, spec.emotion, spec.intensity, seed=spec.index,
                                   has_prop=bool(spec.prop)) if spec.kind == "puppet" else [],
        emotion=spec.emotion, intensity=spec.intensity, body=design.body, prop=spec.prop, phase=spec.index * 1.3)
    performer = _Performer({"design": spec.design}, plan, mirrored=(spec.index % 2 == 1), height=spec.char_height,
                           kind=spec.kind, sprite=spec.sprite)
    return [performer]


def render_scene(spec: SceneSpec, mouth_levels: list, gestures: list, out_path, ffmpeg: str = "ffmpeg",
                 progress=None, envelope=None) -> Path:
    """Rend la scène en MP4 muet 1080x1920 à 30 images/s.

    mouth_levels : ouverture de la bouche par image (0 à 3) ; envelope : volume de la voix par image
    (sinon déduit de mouth_levels) ; gestures n'est conservé que pour compatibilité.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg = Image.open(spec.background).convert("RGB")
    if bg.size != (W, H):
        bg = bg.resize((W, H), Image.LANCZOS)
    if envelope is None:
        envelope = np.asarray(mouth_levels, dtype="float32") / 3.0
    dialogue = bool(spec.characters)
    performers = _build_performers(spec, envelope)
    entrance_mode = spec.entrance or ("pop" if dialogue else entrance_for(spec.index, spec.intensity))
    impact = next((p.plan.emotion for p in performers if p.plan.emotion in IMPACT_EMOTIONS), "neutral")
    frames = max(2, round(spec.duration * FPS))
    height = DIALOGUE_HEIGHT if dialogue else spec.char_height
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "17", "-pix_fmt", "yuv420p", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    shadow = _shadow(int(height * 0.55))
    emph = [1.0] * len(performers)
    try:
        for f in range(frames):
            t = f / FPS
            gt = spec.start_time + t
            g = min(round(gt * FPS), max(len(mouth_levels) - 1, 0))
            active = speaker_at(spec.timeline, gt) if dialogue else 0
            frame = bg.resize((W, H), Image.BILINEAR, box=camera_box(spec.index, t, spec.duration, impact))   # recadrage + zoom en une opération rapide
            order = sorted(range(len(performers)), key=lambda i: i == active)     # celui qui parle est devant
            for i in order:
                perf = performers[i]
                is_active = i == active
                mouth = (mouth_levels[g] if mouth_levels else 0) if is_active else 0
                st = pose_state(perf.plan, gt, t, is_active)
                ent = entrance("pop" if dialogue else entrance_mode, max(t - 0.15 * i, 0.0))
                blinking = ((t + i * 1.3 + spec.index * 0.9) % 3.2) < 0.12
                img = perf.image(st, mouth, blinking, ent["stride"])
                emph[i] += (((1.06 if is_active else 0.97) if dialogue else 1.0) - emph[i]) * 0.25
                squash = 1 + 0.025 * mouth * math.sin(t * 25)
                sx, sy = ent["scale"] * emph[i] / squash, ent["scale"] * emph[i] * squash
                img = img.resize((max(1, round(img.width * sx)), max(1, round(img.height * sy))), Image.BILINEAR)
                sway = (2.2 if is_active else 1.2) * math.sin(2 * math.pi * 0.7 * t + spec.index + i)
                sway_x = 0.0
                if perf.sprite_img is not None:      # image IA découpée : on la penche légèrement
                    img = img.rotate(sway, resample=Image.BILINEAR, expand=True)
                else:                                # marionnette : la tête s'incline déjà ; le corps se balance en douceur
                    sway_x = sway * 3
                hop = -8 * (mouth >= 2) - 4 * abs(math.sin(2 * math.pi * 1.1 * t + i))
                cx = (DIALOGUE_X[i] if dialogue else W // 2) + ent["x_off"] + st["x_off"] + sway_x
                bottom = H - spec.bottom_margin + hop + ent["y_off"] + st["y_off"]
                frame.paste(shadow, (round(cx - shadow.width // 2), round(H - spec.bottom_margin - 24)), shadow)
                frame.paste(img, (round(cx - img.width / 2), round(bottom - img.height)), img)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                break
            if progress and f % 15 == 0:
                progress(f / frames)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() != 0:
            raise AnimationError(f"FFmpeg a échoué : {err[-400:]}")
    except Exception:
        proc.kill()
        out_path.unlink(missing_ok=True)
        raise
    return out_path

"""Animation d'une scène : décor avec mouvement de caméra + personnage animé par la voix.

Les images sont calculées par Pillow puis envoyées à FFmpeg (aucun fichier intermédiaire).
Personnage « puppet » : bouche synchronisée, clignements, gestes, expressions.
Personnage « sprite » (image IA découpée) : rebond et écrasement au rythme de la voix.
"""
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from core.puppet import PuppetDesign, draw_puppet

W, H, FPS = 1080, 1920, 30
MOTIONS = ("zoom_in", "pan_right", "zoom_out", "pan_left")
POP_SECONDS = 0.35
IMPACT_EMOTIONS = ("angry", "surprised")


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


def ease_out_back(x: float) -> float:
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


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


class _PoseCache:
    """Dessine chaque pose une seule fois (le dessin est la partie coûteuse)."""

    def __init__(self, spec: SceneSpec):
        self.spec = spec
        self.cache = {}
        self.design = PuppetDesign(**{k: v for k, v in (spec.design or {}).items()
                                      if k in PuppetDesign.__dataclass_fields__})
        self.sprite_img = None
        if spec.kind == "sprite" and spec.sprite:
            img = Image.open(spec.sprite).convert("RGBA")
            ratio = spec.char_height / img.height
            self.sprite_img = img.resize((max(1, round(img.width * ratio)), spec.char_height), Image.LANCZOS)

    def get(self, mouth: int, blink: bool, arm: int):
        if self.sprite_img is not None:
            return self.sprite_img
        key = (self.spec.emotion, mouth, blink, arm)
        if key not in self.cache:
            self.cache[key] = draw_puppet(self.design, self.spec.emotion, mouth=mouth, blink=blink,
                                          arm_raise=arm / 2, display_height=self.spec.char_height)
        return self.cache[key]


def _shadow(width: int) -> Image.Image:
    sh = Image.new("RGBA", (width, 60), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(sh).ellipse((0, 0, width - 1, 59), fill=(0, 0, 0, 70))
    return sh


def render_scene(spec: SceneSpec, mouth_levels: list, gestures: list, out_path, ffmpeg: str = "ffmpeg",
                 progress=None) -> Path:
    """Rend la scène en MP4 muet 1080x1920 à 30 images/s."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bg = Image.open(spec.background).convert("RGB")
    if bg.size != (W, H):
        bg = bg.resize((W, H), Image.LANCZOS)
    poses = _PoseCache(spec)
    frames = max(2, round(spec.duration * FPS))
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "17", "-pix_fmt", "yuv420p", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    shadow = _shadow(int(spec.char_height * 0.55))
    blink_offset = (spec.index * 0.9) % 3.2
    try:
        for f in range(frames):
            t = f / FPS
            g = min(round((spec.start_time + t) * FPS), max(len(mouth_levels) - 1, 0))
            mouth = mouth_levels[g] if mouth_levels else 0
            arm = gestures[g] if gestures else 0
            blinking = ((t + blink_offset) % 3.2) < 0.12

            frame = bg.transform((W, H), Image.EXTENT, camera_box(spec.index, t, spec.duration, spec.emotion),
                                 Image.BILINEAR)
            pose = poses.get(mouth, blinking, arm)

            pop = ease_out_back(min(t / POP_SECONDS, 1.0))          # entrée en « rebondissant »
            squash = 1 + 0.025 * mouth * math.sin(t * 25)            # petite pulsation quand il parle
            sx, sy = max(pop, 0.01) / squash, max(pop, 0.01) * squash
            img = pose.resize((max(1, round(pose.width * sx)), max(1, round(pose.height * sy))), Image.BILINEAR)
            angle = 2.2 * math.sin(2 * math.pi * 0.7 * t + spec.index)
            img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
            hop = -8 * (mouth >= 2) - 5 * abs(math.sin(2 * math.pi * 1.1 * t))
            cx = W // 2
            bottom = H - spec.bottom_margin + hop
            frame.paste(shadow, (cx - shadow.width // 2, round(H - spec.bottom_margin - 24)), shadow)
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

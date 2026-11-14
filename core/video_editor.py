"""Montage vidéo avec FFmpeg : MP4 vertical 1080x1920 (Phase 3).

Étapes : un clip par scène (recadré/durée exacte) -> concaténation -> incrustation des
sous-titres + audio. Les fichiers temporaires sont supprimés à la fin.
"""
import os
import shutil
import subprocess
from pathlib import Path

from core.subtitle_generator import expand_sentences

WIDTH, HEIGHT, FPS = 1080, 1920, 30
FRAMINGS = ("crop", "blur")
TAIL_SECONDS = 0.4  # petit silence après la dernière parole
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
MOTIONS = ("zoom_in", "pan_right", "zoom_out", "pan_left")  # alternés d'une scène à l'autre
SPRITE_HEIGHT, SPRITE_MARGIN = 720, 330


class VideoEditError(Exception):
    """Erreur lors du montage (FFmpeg absent, échec d'une commande, fichiers manquants...)."""


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise VideoEditError(
            "FFmpeg introuvable. Installe-le (winget install Gyan.FFmpeg), puis rouvre VS Code."
        )
    return path


def compute_scene_durations(texts: list, words: list, audio_duration: float = None) -> list:
    """Durée de chaque scène, calée sur la voix.

    Les frontières sont placées proportionnellement au nombre de mots de chaque scène
    (robuste aux petites différences de découpage entre le script et Edge TTS).
    """
    if not texts:
        raise VideoEditError("Aucune scène à monter.")
    words = expand_sentences(words)
    if not words:
        raise VideoEditError("Horodatage vide : régénère la voix.")
    end_time = audio_duration or (words[-1]["end"] + TAIL_SECONDS)
    counts = [max(1, len(t.split())) for t in texts]
    total = sum(counts)
    starts, cumulative = [], 0
    for c in counts:
        index = min(len(words) - 1, round(cumulative / total * len(words)))
        starts.append(0.0 if not starts else words[index]["start"])
        cumulative += c
    boundaries = starts + [end_time]
    durations = [round(boundaries[i + 1] - boundaries[i], 3) for i in range(len(texts))]
    if any(d <= 0 for d in durations):
        raise VideoEditError("Durées de scènes incohérentes : régénère la voix et les visuels.")
    return durations


def _scene_filter(framing: str) -> list:
    """Arguments FFmpeg pour mettre un clip au format 1080x1920."""
    if framing == "blur":
        graph = (
            f"[0:v]split[a][b];"
            f"[a]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
            f"boxblur=25:5[bg];"
            f"[b]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS}[v]"
        )
        return ["-filter_complex", graph, "-map", "[v]"]
    vf = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
          f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}")
    return ["-vf", vf]


def _image_scene_args(index: int, duration: float, sprite) -> list:
    """Arguments FFmpeg pour animer une image (mouvement de caméra) et poser le personnage dessus."""
    frames = max(2, round(duration * FPS))
    motion = MOTIONS[index % len(MOTIONS)]
    center_y = "y='(ih-ih/zoom)/2'"
    z, x = {
        "zoom_in": (f"1+0.12*on/{frames}", "x='(iw-iw/zoom)/2'"),
        "zoom_out": (f"1.12-0.12*on/{frames}", "x='(iw-iw/zoom)/2'"),
        "pan_right": ("1.12", f"x='(iw-iw/zoom)*on/{frames}'"),
        "pan_left": ("1.12", f"x='(iw-iw/zoom)*(1-on/{frames})'"),
    }[motion]
    # l'image est agrandie 2x avant zoompan : évite les saccades du mouvement
    bg = (f"scale={WIDTH * 2}:{HEIGHT * 2}:flags=lanczos,"
          f"zoompan=z='{z}':{x}:{center_y}:d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1")
    if not sprite:
        return ["-vf", bg]
    bounce = (f"H-h-{SPRITE_MARGIN}+if(lt(t,0.35),(0.35-t)*1000,0)-16*abs(sin(2*PI*1.1*t))")
    graph = (f"[0:v]{bg}[bg];[1:v]scale=-2:{SPRITE_HEIGHT},format=rgba[sp];"
             f"[bg][sp]overlay=x=(W-w)/2:y='{bounce}':shortest=1,fps={FPS}[v]")
    return ["-filter_complex", graph, "-map", "[v]"]


def _run(cmd: list, runner, cwd=None) -> None:
    try:
        result = runner(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise VideoEditError(f"Commande introuvable : {cmd[0]}") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip()[-600:]
        raise VideoEditError(f"FFmpeg a échoué : {tail or 'erreur inconnue'}")


def probe_duration(path, ffprobe: str = None, runner=subprocess.run):
    ffprobe = ffprobe or shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = runner([ffprobe, "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", str(path)],
                     capture_output=True, text=True)
        return float(out.stdout.strip())
    except Exception:
        return None


def assemble_video(clips: list, durations: list, audio_path, ass_path, out_path,
                   framing: str = "crop", ffmpeg: str = None, runner=subprocess.run,
                   sprites: list = None) -> Path:
    """Monte la vidéo finale. clips et durations : une entrée par scène, dans l'ordre.

    Un clip peut être une vidéo (.mp4) ou une image (.jpg/.png, animée par un mouvement de caméra) ;
    `sprites` (optionnel) donne, par scène, le PNG du personnage à poser sur une image.
    """
    if framing not in FRAMINGS:
        raise VideoEditError(f"Cadrage inconnu : {framing}")
    if len(clips) != len(durations) or not clips:
        raise VideoEditError("Clips et durées ne correspondent pas.")
    sprites = list(sprites or [None] * len(clips))
    if len(sprites) != len(clips):
        raise VideoEditError("Sprites et clips ne correspondent pas.")
    for f in [*clips, audio_path, *([ass_path] if ass_path else []), *[sp for sp in sprites if sp]]:
        if not Path(f).exists():
            raise VideoEditError(f"Fichier introuvable : {f}")
    ffmpeg = ffmpeg or find_ffmpeg()

    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.parent / f".tmp_{out_path.stem}"
    part = out_path.with_name(out_path.stem + ".part.mp4")
    base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        # 1. un clip par scène, à la durée exacte (boucle si le clip est trop court)
        scene_files = []
        for i, (clip, dur, sprite) in enumerate(zip(clips, durations, sprites), 1):
            scene = tmp / f"scene_{i}.mp4"
            if Path(clip).suffix.lower() in IMAGE_EXTS:
                inputs = ["-i", str(Path(clip).resolve())]
                if sprite:
                    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(Path(sprite).resolve())]
                args = inputs + ["-t", f"{dur:.3f}", *_image_scene_args(i - 1, dur, sprite)]
            else:
                args = ["-stream_loop", "-1", "-i", str(Path(clip).resolve()), "-t", f"{dur:.3f}",
                        *_scene_filter(framing)]
            _run(base + args + ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                "-pix_fmt", "yuv420p", "-r", str(FPS), str(scene)], runner)
            scene_files.append(scene)
        # 2. concaténation sans ré-encodage
        (tmp / "list.txt").write_text("".join(f"file '{s.name}'\n" for s in scene_files), encoding="utf-8")
        _run(base + ["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "video_only.mp4"],
             runner, cwd=tmp)
        # 3. sous-titres + audio (le .ass est copié dans le dossier de travail : pas de souci de chemin Windows)
        final = base + ["-i", "video_only.mp4", "-i", str(Path(audio_path).resolve())]
        if ass_path:
            shutil.copyfile(ass_path, tmp / "subs.ass")
            final += ["-vf", "ass=subs.ass"]
        final += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                  "-shortest", str(part)]
        _run(final, runner, cwd=tmp)
        os.replace(part, out_path)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path

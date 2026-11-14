"""Sous-titres synchronisés à partir de l'horodatage Edge TTS (Phase 2).

Produit un fichier .srt (universel) et un fichier .ass (stylé, prévu pour l'incrustation FFmpeg
en 1080x1920).
"""
import json
import re
from pathlib import Path

END_PUNCT = (".", "!", "?", "…")

# Styles ASS par réglage `style.subtitles` des chaînes (couleurs au format &HAABBGGRR)
STYLES = {
    "modernes": {"font": "Arial", "size": 78, "primary": "&H00FFFFFF", "outline": 6, "uppercase": False,
                 "max_words": 4, "max_chars": 24},
    "marqués": {"font": "Arial", "size": 84, "primary": "&H00FFFFFF", "outline": 8, "uppercase": False,
                "max_words": 4, "max_chars": 22},
    "dynamiques": {"font": "Arial", "size": 88, "primary": "&H0000FFFF", "outline": 8, "uppercase": True,
                   "max_words": 3, "max_chars": 16},
}
DEFAULT_STYLE = "modernes"


class SubtitleError(Exception):
    """Erreur lors de la génération des sous-titres."""


def load_words(words_path) -> list:
    try:
        words = json.loads(Path(words_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SubtitleError(f"Horodatage illisible ({exc}). Régénère la voix.") from exc
    if not words:
        raise SubtitleError("Aucun horodatage : régénère la voix.")
    return words


def _expand_sentences(words: list) -> list:
    """Si Edge TTS n'a fourni que des phrases, répartit le temps mot par mot (approximation)."""
    expanded = []
    for item in words:
        if item.get("kind") != "SentenceBoundary":
            expanded.append(item)
            continue
        tokens = item["text"].split()
        if not tokens:
            continue
        step = (item["end"] - item["start"]) / len(tokens)
        for i, tok in enumerate(tokens):
            expanded.append({"text": tok, "start": item["start"] + i * step,
                             "end": item["start"] + (i + 1) * step})
    return expanded


expand_sentences = _expand_sentences  # utilisé aussi par le montage


def words_to_cues(words: list, max_words: int = 4, max_chars: int = 28, pause: float = 0.35) -> list:
    """Regroupe les mots en sous-titres courts : [{'start', 'end', 'text'}]."""
    words = _expand_sentences(words)
    cues, current = [], []

    def flush():
        if current:
            cues.append({"start": current[0]["start"], "end": current[-1]["end"],
                         "text": " ".join(w["text"] for w in current)})
            current.clear()

    for w in words:
        if current and w["start"] - current[-1]["end"] > pause:
            flush()
        current.append(w)
        text_len = len(" ".join(x["text"] for x in current))
        if len(current) >= max_words or text_len >= max_chars or w["text"].endswith(END_PUNCT):
            flush()
    flush()
    return cues


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(t: float) -> str:
    cs = round(t * 100)
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6_000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def to_srt(cues: list) -> str:
    blocks = [f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{c['text']}\n"
              for i, c in enumerate(cues, 1)]
    return "\n".join(blocks)


def to_ass(cues: list, style_name: str = DEFAULT_STYLE, labels: list = None) -> str:
    st = STYLES.get(style_name, STYLES[DEFAULT_STYLE])
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{st['font']},{st['size']},{st['primary']},&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{st['outline']},2,2,80,80,420,1\n"
        f"Style: Label,{st['font']},68,&H00FFFFFF,&H00FFFFFF,&H00502A14,&H00000000,"
        f"-1,0,0,0,100,100,0,0,3,16,0,8,80,80,300,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for c in cues:
        text = re.sub(r"[{}]", "", c["text"]).replace("\n", " ")
        if st["uppercase"]:
            text = text.upper()
        lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,,{text}")
    for lab in labels or []:
        text = re.sub(r"[{}]", "", lab["text"]).replace("\n", " ")
        pop = r"{\fad(150,150)\fscx85\fscy85\t(0,180,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 1,{_ass_time(lab['start'])},{_ass_time(lab['end'])},Label,,0,0,0,,{pop}{text}")
    return header + "\n".join(lines) + "\n"


def cue_params(style_name: str) -> dict:
    """Taille maximale des sous-titres selon le style (les gros styles sont coupés plus court)."""
    st = STYLES.get(style_name, STYLES[DEFAULT_STYLE])
    return {"max_words": st["max_words"], "max_chars": st["max_chars"]}


def generate_subtitles(words_path, channel_cfg: dict, out_dir=None, basename: str = None) -> dict:
    """Crée <basename>.srt et <basename>.ass à côté du fichier d'horodatage."""
    words_path = Path(words_path)
    words = load_words(words_path)
    style_name = channel_cfg.get("style", {}).get("subtitles", DEFAULT_STYLE)
    cues = words_to_cues(words, **cue_params(style_name))
    if not cues:
        raise SubtitleError("Aucun sous-titre généré.")
    out_dir = Path(out_dir or words_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    basename = basename or words_path.name.replace(".words.json", "")
    srt_path, ass_path = out_dir / f"{basename}.srt", out_dir / f"{basename}.ass"
    srt_path.write_text(to_srt(cues), encoding="utf-8")
    ass_path.write_text(to_ass(cues, style_name), encoding="utf-8")
    return {"srt_path": srt_path, "ass_path": ass_path, "cues": cues}

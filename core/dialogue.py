"""Mode dialogue : deux personnages qui discutent (script en répliques, voix, découpage en scènes)."""
import json
import re
from math import ceil
from pathlib import Path

from core.config import ROOT
from core.script_generator import TONES, ScriptGenerationError, call_groq, target_words
from database import db

VOICES = {
    "fr-FR-HenriNeural": "Henri (homme, posé)",
    "fr-FR-RemyMultilingualNeural": "Rémy (homme, chaleureux)",
    "fr-FR-DeniseNeural": "Denise (femme, claire)",
    "fr-FR-VivienneMultilingualNeural": "Vivienne (femme, expressive)",
    "fr-FR-EloiseNeural": "Éloïse (voix d'enfant)",
}
DEFAULT_VOICES = ["fr-FR-HenriNeural", "fr-FR-DeniseNeural"]
DEFAULT_ROLES = ["le curieux : il pose les questions et réagit avec surprise",
                 "celui qui explique : il répond avec humour et des exemples simples"]
CONFIG_DIR = ROOT / "media" / "dialogue"
TAIL_SECONDS = 0.4


class DialogueError(Exception):
    """Erreur dans le dialogue (script mal formé, personnage inconnu...)."""


# --- Configuration d'un projet en dialogue --------------------------------------------------------------

def save_config(project_id: int, speakers: list, db_path=None) -> Path:
    """speakers : [{'name', 'character_id', 'voice', 'role'}, {...}]. Enregistré comme asset du projet."""
    path = CONFIG_DIR / f"project_{project_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"speakers": speakers}, ensure_ascii=False, indent=1), encoding="utf-8")
    db.replace_asset(project_id, "dialogue", path, source="dialogue", db_path=db_path)
    return path


def load_config(project_id: int, db_path=None):
    """Configuration du dialogue, ou None si le projet n'est pas en dialogue."""
    for asset in reversed(db.list_assets(project_id, "dialogue", db_path=db_path)):
        if Path(asset["file_path"]).exists():
            try:
                return json.loads(Path(asset["file_path"]).read_text(encoding="utf-8"))
            except ValueError:
                return None
    return None


# --- Lecture du script en répliques ---------------------------------------------------------------------

_LINE = re.compile(r"^[\s*_#>\-•]*(?P<name>[^:：\n]{1,40}?)[\s*_]*[:：]\s*(?P<text>.*)$")


def _clean_spoken(text: str) -> str:
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)       # didascalies : (rit), [soupir]
    text = re.sub(r"[*_#`]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_dialogue(text: str, names: list) -> list:
    """Retourne [(index_du_personnage, réplique)]. Une ligne sans nom prolonge la réplique précédente."""
    lookup = {n.strip().casefold(): i for i, n in enumerate(names)}
    lines = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = _LINE.match(raw)
        if m and m.group("name").strip().strip("*_ ").casefold() in lookup:
            lines.append([lookup[m.group("name").strip().strip("*_ ").casefold()], m.group("text")])
        elif m and not lines:
            raise DialogueError(f"Personnage inconnu « {m.group('name').strip()} ». Noms attendus : {', '.join(names)}.")
        elif lines:
            lines[-1][1] += " " + raw
        else:
            raise DialogueError("Chaque réplique doit commencer par le nom du personnage, par exemple « "
                                f"{names[0]} : Bonjour ! ».")
    result = [(i, _clean_spoken(t)) for i, t in lines]
    result = [(i, t) for i, t in result if t]
    if len(result) < 2 or len({i for i, _ in result}) < 2:
        raise DialogueError("Un dialogue demande au moins une réplique de chacun des deux personnages.")
    return result


def to_script_text(lines: list, names: list) -> str:
    return "\n".join(f"{names[i]} : {t}" for i, t in lines)


# --- Découpage en scènes ---------------------------------------------------------------------------------

def group_segments(segments: list, max_scenes: int = 8, min_words: int = 10) -> list:
    """Regroupe des répliques consécutives en scènes : [{'text', 'segments': [premier, dernier]}]."""
    if not segments:
        return []
    total = sum(len(s["text"].split()) for s in segments)
    per_scene = max(min_words, ceil(total / max_scenes))
    scenes, current, count = [], [], 0

    def flush():
        nonlocal current, count
        if current:
            scenes.append({"text": " ".join(segments[i]["text"] for i in current), "segments": [current[0], current[-1]]})
            current, count = [], 0

    for i, seg in enumerate(segments):
        current.append(i)
        count += len(seg["text"].split())
        if count >= per_scene:
            flush()
    if current:
        if scenes and count < max(3, min_words // 2):  # reste très court : on l'ajoute à la scène précédente
            scenes[-1]["text"] += " " + " ".join(segments[i]["text"] for i in current)
            scenes[-1]["segments"][1] = current[-1]
            current = []
        else:
            flush()
    while len(scenes) > max_scenes:
        last = scenes.pop()
        scenes[-1]["text"] += " " + last["text"]
        scenes[-1]["segments"][1] = last["segments"][1]
    return scenes


def dialogue_scene_durations(plan: list, segments: list, audio_duration: float = None) -> list:
    """Durée de chaque scène, calée exactement sur les répliques (début de la première réplique de la scène)."""
    starts = [0.0 if i == 0 else float(segments[e["segments"][0]]["start"]) for i, e in enumerate(plan)]
    end = audio_duration or (float(segments[-1]["end"]) + TAIL_SECONDS)
    bounds = starts + [end]
    durations = [round(bounds[i + 1] - bounds[i], 3) for i in range(len(plan))]
    if any(d <= 0 for d in durations):
        raise DialogueError("Durées de scènes incohérentes : régénère la voix et les illustrations.")
    return durations


def speaker_at(timeline: list, t: float):
    """Index du personnage qui parle à l'instant t (None pendant une pause)."""
    for seg in timeline or []:
        if seg["start"] <= t < seg["end"]:
            return seg["speaker"]
    return None


# --- Écriture du dialogue avec Groq ------------------------------------------------------------------------

def build_dialogue_messages(topic: str, channel_cfg: dict, speakers: list, tone: str = None) -> list:
    words = target_words(channel_cfg["duration"])
    who = "\n".join(f"- {s['name']} : {s.get('role') or 'personnage'}" for s in speakers)
    system = ("Tu es scénariste de dialogues pour YouTube Shorts. Tu écris uniquement les répliques, prêtes à "
              "être lues à voix haute : pas de didascalies, pas d'émojis, pas de markdown.")
    user = (
        f"Chaîne : {channel_cfg['name']} ({channel_cfg.get('niche', '')}) ; langue : {channel_cfg['language']}.\n"
        f"Durée visée : {channel_cfg['duration']} secondes, soit environ {words} mots au total.\n\n"
        f"Sujet : {topic}\n\nPersonnages :\n{who}\n\n"
        f"Format STRICT : une réplique par ligne, sous la forme « Nom : texte », avec exactement ces noms "
        f"({' et '.join(s['name'] for s in speakers)}). Alterne les personnages ; réplique courte (20 mots maximum).\n"
        "Structure : la toute première réplique est une accroche (question ou contradiction qui surprend, sans "
        "salutation) ; ensuite un échange vivant où chacun réagit à l'autre ; une chute ou une question finale.\n"
        "Règle : n'invente aucun fait, chiffre ou date ; si une information est incertaine, dis-le."
        + (f"\n{TONES[tone][1]}" if tone in TONES and TONES[tone][1] else "")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_dialogue_script(topic: str, channel_cfg: dict, speakers: list, client=None, model: str = None,
                             tone: str = None) -> str:
    """Retourne le dialogue au format « Nom : texte » (une réplique par ligne), vérifié."""
    if not topic.strip():
        raise ScriptGenerationError("Le sujet est vide.")
    if client is None:
        import os

        if not os.getenv("GROQ_API_KEY"):
            raise ScriptGenerationError("GROQ_API_KEY absente : renseigne-la dans le fichier .env.")
        from groq import Groq

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    names = [s["name"] for s in speakers]
    try:
        text = call_groq(client, build_dialogue_messages(topic, channel_cfg, speakers, tone), max_tokens=3000,
                         model=model)
    except Exception as exc:
        raise ScriptGenerationError(f"Appel Groq échoué : {exc}") from exc
    try:
        return to_script_text(parse_dialogue(text, names), names)
    except DialogueError as exc:
        raise ScriptGenerationError(f"Le dialogue renvoyé par Groq est mal formé : {exc}") from exc

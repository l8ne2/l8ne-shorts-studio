"""Chargement de la configuration des chaînes (fichiers YAML)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHANNELS_DIR = ROOT / "channels"

REQUIRED_KEYS = ("name", "language", "duration", "format")


def load_channel(slug: str, channels_dir: Path = CHANNELS_DIR) -> dict:
    """Charge la configuration d'une chaîne à partir de son slug (nom du fichier)."""
    path = channels_dir / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Configuration introuvable : {path}")
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        raise ValueError(f"{path.name} : clés manquantes {missing}")
    config["slug"] = slug
    return config


def load_all_channels(channels_dir: Path = CHANNELS_DIR) -> dict:
    """Retourne {slug: configuration} pour toutes les chaînes."""
    return {
        p.stem: load_channel(p.stem, channels_dir)
        for p in sorted(channels_dir.glob("*.yaml"))
    }

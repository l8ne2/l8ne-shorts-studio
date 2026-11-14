"""Accès à la base SQLite : chaînes, projets, assets, exports."""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from core.config import ROOT, load_all_channels

DEFAULT_DB_PATH = ROOT / "database" / "studio.db"

STATUSES = [
    "DRAFT",
    "SCRIPT_READY",
    "AUDIO_READY",
    "ASSETS_READY",
    "RENDERING",
    "COMPLETED",
    "ERROR",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    niche TEXT,
    config TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES channels(id),
    title TEXT NOT NULL,
    topic TEXT,
    script TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    error TEXT,
    style TEXT NOT NULL DEFAULT 'stock',
    character_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    asset_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source TEXT
);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    style TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS character_expressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    emotion TEXT NOT NULL,
    file_path TEXT NOT NULL,
    UNIQUE(character_id, emotion)
);
CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    file_path TEXT NOT NULL,
    duration INTEGER,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dict_factory(cursor, row) -> dict:
    """Les lignes sont de simples dict : copiables (Streamlit copie les choix des listes déroulantes)."""
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def get_connection(db_path=None) -> sqlite3.Connection:
    path = Path(db_path or os.getenv("L8NE_DB_PATH") or DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn) -> None:
    """Ajoute les colonnes apparues après la première version, sans toucher aux données."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)")}
    if "style" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN style TEXT NOT NULL DEFAULT 'stock'")
    if "character_id" not in cols:
        conn.execute("ALTER TABLE projects ADD COLUMN character_id INTEGER")


def init_db(db_path=None, channels_dir=None) -> None:
    """Crée les tables et synchronise les chaînes depuis les fichiers YAML."""
    kwargs = {"channels_dir": channels_dir} if channels_dir else {}
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        for slug, cfg in load_all_channels(**kwargs).items():
            conn.execute(
                """INSERT INTO channels (slug, name, niche, config)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(slug) DO UPDATE SET
                     name=excluded.name, niche=excluded.niche, config=excluded.config""",
                (slug, cfg["name"], cfg.get("niche"), json.dumps(cfg, ensure_ascii=False)),
            )


def list_channels(db_path=None) -> list:
    with get_connection(db_path) as conn:
        return conn.execute("SELECT * FROM channels ORDER BY id").fetchall()


def create_project(channel_id: int, title: str, topic: str = "", style: str = "stock",
                   character_id: int = None, db_path=None) -> int:
    now = _now()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO projects (channel_id, title, topic, status, style, character_id, created_at, updated_at)
               VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?)""",
            (channel_id, title, topic, style, character_id, now, now),
        )
        return cur.lastrowid


def get_project(project_id: int, db_path=None):
    with get_connection(db_path) as conn:
        return conn.execute(
            """SELECT p.*, c.name AS channel_name, c.slug AS channel_slug
               FROM projects p JOIN channels c ON c.id = p.channel_id
               WHERE p.id = ?""",
            (project_id,),
        ).fetchone()


def list_projects(channel_id=None, status=None, limit=None, db_path=None) -> list:
    query = """SELECT p.*, c.name AS channel_name, c.slug AS channel_slug
               FROM projects p JOIN channels c ON c.id = p.channel_id WHERE 1=1"""
    params = []
    if channel_id:
        query += " AND p.channel_id = ?"
        params.append(channel_id)
    if status:
        query += " AND p.status = ?"
        params.append(status)
    query += " ORDER BY p.updated_at DESC, p.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    with get_connection(db_path) as conn:
        return conn.execute(query, params).fetchall()


def update_script(project_id: int, script: str, db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE projects SET script = ?, updated_at = ? WHERE id = ?",
            (script, _now(), project_id),
        )


def set_status(project_id: int, status: str, error: str = None, db_path=None) -> None:
    """Change le statut. En cas d'erreur, le projet est conservé avec le message."""
    if status not in STATUSES:
        raise ValueError(f"Statut invalide : {status}")
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE projects SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, _now(), project_id),
        )


def replace_asset(project_id: int, asset_type: str, file_path: str, source: str = None, db_path=None) -> None:
    """Enregistre un asset en remplaçant l'éventuel asset précédent du même type."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM assets WHERE project_id = ? AND asset_type = ?", (project_id, asset_type))
        conn.execute(
            "INSERT INTO assets (project_id, asset_type, file_path, source) VALUES (?, ?, ?, ?)",
            (project_id, asset_type, str(file_path), source),
        )


def list_assets(project_id: int, asset_type: str = None, db_path=None) -> list:
    query, params = "SELECT * FROM assets WHERE project_id = ?", [project_id]
    if asset_type:
        query += " AND asset_type = ?"
        params.append(asset_type)
    with get_connection(db_path) as conn:
        return conn.execute(query + " ORDER BY id", params).fetchall()


def replace_assets(project_id: int, asset_type: str, items: list, db_path=None) -> None:
    """Remplace tous les assets d'un type. items = [(file_path, source), ...] (l'ordre est conservé)."""
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM assets WHERE project_id = ? AND asset_type = ?", (project_id, asset_type))
        conn.executemany(
            "INSERT INTO assets (project_id, asset_type, file_path, source) VALUES (?, ?, ?, ?)",
            [(project_id, asset_type, str(path), source) for path, source in items],
        )


def add_export(project_id: int, file_path: str, duration: int = None, db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO exports (project_id, file_path, duration, created_at) VALUES (?, ?, ?, ?)",
            (project_id, str(file_path), duration, _now()),
        )


def list_exports(project_id: int, db_path=None) -> list:
    with get_connection(db_path) as conn:
        return conn.execute(
            "SELECT * FROM exports WHERE project_id = ? ORDER BY id DESC", (project_id,)
        ).fetchall()


# --- Personnages (studio) ---------------------------------------------------------------------

def create_character(name: str, style: str, description: str, db_path=None) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO characters (name, style, description, created_at) VALUES (?, ?, ?, ?)",
            (name, style, description, _now()),
        )
        return cur.lastrowid


def get_character(character_id: int, db_path=None):
    with get_connection(db_path) as conn:
        return conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()


def list_characters(style: str = None, db_path=None) -> list:
    query, params = "SELECT * FROM characters", []
    if style:
        query += " WHERE style = ?"
        params.append(style)
    with get_connection(db_path) as conn:
        return conn.execute(query + " ORDER BY id DESC", params).fetchall()


def update_character(character_id: int, name: str, description: str, db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE characters SET name = ?, description = ? WHERE id = ?",
                     (name, description, character_id))


def set_expression(character_id: int, emotion: str, file_path, db_path=None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO character_expressions (character_id, emotion, file_path) VALUES (?, ?, ?)
               ON CONFLICT(character_id, emotion) DO UPDATE SET file_path = excluded.file_path""",
            (character_id, emotion, str(file_path)),
        )


def list_expressions(character_id: int, db_path=None) -> dict:
    """Retourne {emotion: chemin}."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT emotion, file_path FROM character_expressions WHERE character_id = ?", (character_id,)
        ).fetchall()
    return {r["emotion"]: r["file_path"] for r in rows}

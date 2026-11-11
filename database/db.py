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


def get_connection(db_path=None) -> sqlite3.Connection:
    path = Path(db_path or os.getenv("L8NE_DB_PATH") or DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None, channels_dir=None) -> None:
    """Crée les tables et synchronise les chaînes depuis les fichiers YAML."""
    kwargs = {"channels_dir": channels_dir} if channels_dir else {}
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
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


def create_project(channel_id: int, title: str, topic: str = "", db_path=None) -> int:
    now = _now()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO projects (channel_id, title, topic, status, created_at, updated_at)
               VALUES (?, ?, ?, 'DRAFT', ?, ?)""",
            (channel_id, title, topic, now, now),
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

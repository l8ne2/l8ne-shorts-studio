import pytest

from database import db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_chaines_synchronisees(db_path):
    assert len(db.list_channels(db_path)) == 3


def test_init_idempotent(db_path):
    db.init_db(db_path)
    assert len(db.list_channels(db_path)) == 3


def test_creation_projet(db_path):
    ch = db.list_channels(db_path)[0]
    pid = db.create_project(ch["id"], "Test", "sujet", db_path=db_path)
    p = db.get_project(pid, db_path)
    assert p["status"] == "DRAFT"
    assert p["channel_name"] == ch["name"]


def test_script_et_statut(db_path):
    ch = db.list_channels(db_path)[0]
    pid = db.create_project(ch["id"], "Test", db_path=db_path)
    db.update_script(pid, "Bonjour", db_path)
    db.set_status(pid, "SCRIPT_READY", db_path=db_path)
    p = db.get_project(pid, db_path)
    assert p["script"] == "Bonjour" and p["status"] == "SCRIPT_READY"


def test_erreur_conserve_le_projet(db_path):
    ch = db.list_channels(db_path)[0]
    pid = db.create_project(ch["id"], "Test", db_path=db_path)
    db.update_script(pid, "Mon script", db_path)
    db.set_status(pid, "ERROR", error="Échec voix", db_path=db_path)
    p = db.get_project(pid, db_path)
    assert p["script"] == "Mon script" and p["error"] == "Échec voix"


def test_statut_invalide(db_path):
    ch = db.list_channels(db_path)[0]
    pid = db.create_project(ch["id"], "Test", db_path=db_path)
    with pytest.raises(ValueError):
        db.set_status(pid, "N_IMPORTE_QUOI", db_path=db_path)

import pytest

from core.config import load_all_channels, load_channel


def test_trois_chaines_chargees():
    chaines = load_all_channels()
    assert set(chaines) == {"tech_ia", "mysteries", "cinema_series"}


def test_chaque_chaine_a_sa_config():
    cfg = load_channel("tech_ia")
    assert cfg["name"] == "Tech & IA"
    assert cfg["format"] == "9:16"


def test_chaine_inconnue():
    with pytest.raises(FileNotFoundError):
        load_channel("inexistante")

from types import SimpleNamespace

import pytest

from core.config import load_channel
from core.script_generator import (
    ScriptGenerationError, build_messages, check_script, clean_script, generate_script,
)


class FakeClient:
    def __init__(self, content=None, error=None):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content, self._error = content, error

    def _create(self, **kwargs):
        if self._error:
            raise self._error
        msg = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_prompt_contient_sujet_et_duree():
    cfg = load_channel("tech_ia")
    user = build_messages("Les agents IA", cfg)[1]["content"]
    assert "Les agents IA" in user and "45 secondes" in user and "112 mots" in user


def test_generation_nettoie_le_texte():
    cfg = load_channel("tech_ia")
    script = generate_script("IA", cfg, client=FakeClient("**Bonjour** tout le monde."))
    assert script == "Bonjour tout le monde."


def test_erreur_api_encapsulee():
    cfg = load_channel("tech_ia")
    with pytest.raises(ScriptGenerationError):
        generate_script("IA", cfg, client=FakeClient(error=RuntimeError("429")))


def test_reponse_vide():
    cfg = load_channel("tech_ia")
    with pytest.raises(ScriptGenerationError):
        generate_script("IA", cfg, client=FakeClient(""))


def test_cle_absente(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ScriptGenerationError):
        generate_script("IA", load_channel("tech_ia"))


def test_controle_qualite():
    assert check_script("Un. Un. Un.", 45)  # court + répété
    assert clean_script('"abc"') == "abc"

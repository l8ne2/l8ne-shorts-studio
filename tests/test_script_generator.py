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


class RecordingClient:
    """Échoue en 404 pour certains modèles, enregistre les appels."""

    def __init__(self, unavailable=()):
        self.calls, self.unavailable = [], set(unavailable)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] in self.unavailable:
            raise RuntimeError("Error code: 404 - model_not_found: The model does not exist")
        msg = SimpleNamespace(content="Texte final.")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_repli_si_modele_introuvable(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    client = RecordingClient(unavailable={"openai/gpt-oss-120b"})
    script = generate_script("IA", load_channel("tech_ia"), client=client)
    assert script == "Texte final."
    assert [c["model"] for c in client.calls] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_effort_de_raisonnement_seulement_pour_gpt_oss(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    client = RecordingClient(unavailable={"openai/gpt-oss-120b", "openai/gpt-oss-20b"})
    generate_script("IA", load_channel("tech_ia"), client=client)
    assert client.calls[0]["extra_body"] == {"reasoning_effort": "low"}
    assert "extra_body" not in client.calls[-1]  # llama : paramètre non envoyé


def test_modele_impose_par_env(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "llama-3.1-8b-instant")
    client = RecordingClient()
    generate_script("IA", load_channel("tech_ia"), client=client)
    assert [c["model"] for c in client.calls] == ["llama-3.1-8b-instant"]


def test_aucun_modele_disponible(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    client = RecordingClient(unavailable={"openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"})
    with pytest.raises(ScriptGenerationError):
        generate_script("IA", load_channel("tech_ia"), client=client)

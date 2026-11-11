import json

import pytest

from core.subtitle_generator import (
    SubtitleError, generate_subtitles, to_ass, to_srt, words_to_cues,
)


def W(text, start, end, kind="WordBoundary"):
    return {"text": text, "start": start, "end": end, "kind": kind}


WORDS = [W("Bonjour", 0.0, 0.5), W("à", 0.5, 0.6), W("tous.", 0.6, 1.0),
         W("Voici", 1.1, 1.4), W("une", 1.4, 1.5), W("histoire", 1.5, 2.0),
         W("vraie", 2.0, 2.4), W("incroyable", 2.4, 3.0)]


def test_regroupement_par_ponctuation_et_taille():
    cues = words_to_cues(WORDS)
    assert cues[0] == {"start": 0.0, "end": 1.0, "text": "Bonjour à tous."}
    assert all(len(c["text"].split()) <= 4 for c in cues)
    assert " ".join(c["text"] for c in cues) == " ".join(w["text"] for w in WORDS)


def test_coupure_sur_pause():
    cues = words_to_cues([W("un", 0, 0.2), W("deux", 1.5, 1.8)])
    assert len(cues) == 2


def test_format_srt():
    srt = to_srt([{"start": 0.0, "end": 1.2346, "text": "Salut"}, {"start": 3661.5, "end": 3662, "text": "Fin"}])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,235\nSalut\n")
    assert "2\n01:01:01,500 --> 01:01:02,000\nFin" in srt


def test_format_ass_et_styles():
    cue = [{"start": 0.0, "end": 1.0, "text": "salut {x}"}]
    ass = to_ass(cue, "dynamiques")
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,SALUT X" in ass  # majuscules, accolades retirées
    assert "&H0000FFFF" in ass  # jaune
    assert "salut x" in to_ass(cue, "style-inconnu")  # style inconnu : retombe sur « modernes »


def test_repli_phrases_reparties_par_mot():
    cues = words_to_cues([W("un deux trois quatre", 0, 4, kind="SentenceBoundary")], max_words=2)
    assert [c["text"] for c in cues] == ["un deux", "trois quatre"]
    assert cues[0]["end"] == pytest.approx(2.0)


def test_generation_fichiers(tmp_path):
    wp = tmp_path / "project_5.words.json"
    wp.write_text(json.dumps(WORDS), encoding="utf-8")
    res = generate_subtitles(wp, {"style": {"subtitles": "marqués"}})
    assert res["srt_path"].name == "project_5.srt" and res["ass_path"].exists()
    assert "Bonjour à tous." in res["srt_path"].read_text(encoding="utf-8")


def test_erreurs(tmp_path):
    with pytest.raises(SubtitleError):
        generate_subtitles(tmp_path / "absent.words.json", {})
    vide = tmp_path / "v.words.json"
    vide.write_text("[]")
    with pytest.raises(SubtitleError):
        generate_subtitles(vide, {})

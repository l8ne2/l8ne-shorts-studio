import numpy as np
import pytest

from core import acting
from core.acting import ActorPlan, Event, build_events, entrance, pose_state, reaction_windows
from core.puppet import PRESETS, PROPS, PuppetDesign, draw_body_layers, draw_head_layer, draw_puppet, solve_arm


def speech(seconds=6.0, fps=30):
    """Voix simulée : des phrases de ~1,2 s séparées de silences, avec des temps forts."""
    t = np.arange(int(seconds * fps)) / fps
    return (np.clip(np.sin(2 * np.pi * 0.42 * t), 0, None) * (0.7 + 0.5 * np.abs(np.sin(2 * np.pi * 2.0 * t)))).astype("float32")


def test_gestes_sur_les_temps_forts():
    env = speech()
    ev = build_events(env, 0.0, 6.0, emotion="happy", intensity="normal")
    assert ev and all(0.4 <= e.t0 <= 5.55 for e in ev)
    assert all(b.t0 - a.t0 >= 1.5 for a, b in zip(ev, ev[1:]))              # écart minimal « naturel »
    assert {e.gesture for e in ev} <= set(acting.EMOTION_GESTURES["happy"])  # gestes cohérents avec l'émotion
    assert build_events(env, 0.0, 6.0, intensity="comic").__len__() >= len(ev)   # comique : plus de gestes
    assert len(build_events(env, 0.0, 6.0, intensity="calm")) <= len(ev)


def test_aucun_geste_en_silence_ni_pour_l_auditeur():
    assert build_events(np.zeros(180), 0.0, 6.0) == []
    ev = build_events(speech(), 0.0, 6.0, active_ranges=[(0.0, 1.0)])
    assert all(e.t0 < 1.0 for e in ev)                                         # il ne gesticule que quand il parle


def test_deterministe():
    a = build_events(speech(), 0.0, 6.0, emotion="neutral", seed=3)
    assert a == build_events(speech(), 0.0, 6.0, emotion="neutral", seed=3)
    assert [e.gesture for e in a] != [e.gesture for e in build_events(speech(), 0.0, 6.0, emotion="neutral", seed=4)] or len(a) < 2


def test_etat_pendant_un_geste():
    plan = ActorPlan([Event(1.0, 1.0, "shrug")], "neutral", "expressive", "cozy")
    assert pose_state(plan, 0.5, 0.5)["right_hand"] is None                    # avant : bras au repos
    mid = pose_state(plan, 1.4, 1.4)
    assert mid["gesture"] == "shrug" and mid["right_hand"] and mid["left_hand"]  # haussement d'épaules : deux bras
    assert mid["emotion"] == "sad"                                             # le visage accompagne le geste
    assert pose_state(plan, 2.2, 2.2)["right_hand"] is None                    # après : retour au repos
    calm = ActorPlan([Event(1.0, 1.0, "shrug")], "neutral", "normal", "cozy")
    assert pose_state(calm, 1.4, 1.4)["emotion"] == "neutral"                  # pas de grimace en mode naturel


def test_objet_tenu_et_main_gauche():
    plan = ActorPlan([Event(1.0, 1.0, "explain")], "neutral", "normal", "cozy", prop="phone")
    st = pose_state(plan, 0.2, 0.2)
    assert st["right_hand"] == acting.HOLD["phone"][0] and st["front_arms"] and st["prop"] == "phone"
    st = pose_state(plan, 1.4, 1.4)
    assert st["right_hand"] == acting.HOLD["phone"][0] and st["left_hand"]      # il gesticule de l'autre main


def test_saut_et_tremblement():
    jump = ActorPlan([Event(1.0, 1.0, "cheer")], "surprised", "expressive", "cozy")
    assert pose_state(jump, 1.15, 1.15)["y_off"] < -20
    angry = ActorPlan([Event(1.0, 1.0, "point")], "angry", "comic", "cozy")
    assert any(abs(pose_state(angry, 1.0 + k / 30, 1.0 + k / 30)["x_off"]) > 3 for k in range(8))
    assert pose_state(ActorPlan([Event(1.0, 1.0, "cheer")], "surprised", "calm", "cozy"), 1.15, 1.15)["y_off"] == 0


def test_tete_quantifiee_et_bornee():
    plan = ActorPlan([], "thinking", "comic", "cozy")
    for k in range(60):
        st = pose_state(plan, k / 10, k / 10)
        assert st["head_tilt"] % 3 == 0 and -15 <= st["head_tilt"] <= 15 and st["head_dy"] % 6 == 0   # peu de variantes à dessiner


def test_entrees():
    assert entrance("pop", 0.0)["scale"] == pytest.approx(0.01, abs=0.02) and entrance("pop", 1.0)["scale"] == pytest.approx(1.0)
    w0, w1 = entrance("walk_left", 0.0), entrance("walk_left", 0.89)
    assert w0["x_off"] < -600 and abs(w1["x_off"]) < 5 and w0["stride"] != w1["stride"] + 1e9
    assert entrance("walk_right", 0.0)["x_off"] > 600
    assert entrance("drop", 0.0)["y_off"] < -800 and entrance("drop", 0.8)["y_off"] == 0
    assert acting.entrance_for(1, "calm") == "pop" and acting.entrance_for(1, "normal") == "walk_left"


def test_reactions_de_l_auditeur():
    tl = [{"speaker": 0, "start": 0, "end": 2}, {"speaker": 1, "start": 2.2, "end": 4}]
    assert reaction_windows(tl, 1, "normal") == []                              # seulement expressif / comique
    win = reaction_windows(tl, 1, "expressive")
    assert len(win) == 1 and win[0][0] == pytest.approx(1.75)
    assert pose_state(ActorPlan([], "neutral", "expressive", "cozy", reactions=win), 1.9, 1.9)["emotion"] in acting.REACTIONS


# --- dessin ----------------------------------------------------------------------------------------------------

def test_cinematique_inverse():
    sh = (395, 480)
    for target in ((560, 420), (340, 420), (470, 150), (395, 480), (900, 900)):
        elbow, hand = solve_arm(sh, target)
        assert np.hypot(elbow[0] - sh[0], elbow[1] - sh[1]) == pytest.approx(acting_len := 120, abs=1.0)
        assert np.hypot(hand[0] - elbow[0], hand[1] - elbow[1]) == pytest.approx(100, abs=1.0)   # os de longueur constante
    _, hand = solve_arm(sh, (560, 420))
    assert hand == pytest.approx((560, 420), abs=1)                              # cible atteignable : atteinte
    _, far = solve_arm(sh, (900, 900))
    assert np.hypot(far[0] - sh[0], far[1] - sh[1]) <= 220                       # cible trop loin : bras tendu


def test_calques_de_meme_taille_et_reutilisables():
    d = PRESETS["cozy_beige"][1]
    back, front = draw_body_layers(d, display_height=400, right_hand=(500, 400), prop="phone", front_arms=True)
    head = draw_head_layer(d, "happy", 2, False, 6, 6, 400)
    assert back.size == head.size == front.size and back.height == 400
    assert draw_body_layers(d, display_height=400)[1] is None                    # rien devant : pas de calque inutile
    assert draw_puppet(d, display_height=400).size == back.size                  # le personnage ne « saute » pas


def test_taille_fixe_quelle_que_soit_la_pose():
    d = PRESETS["classic_stick"][1]
    sizes = {draw_puppet(d, e, mouth=m, display_height=300, right_hand=h, head_tilt=t).size
             for e, m, h, t in (("neutral", 0, None, 0), ("surprised", 2, (560, 200), 9), ("tired", 0, (340, 420), -9))}
    assert len(sizes) == 1


@pytest.mark.parametrize("prop", PROPS)
def test_objets(prop):
    d = PRESETS["cozy_beige"][1]
    with_prop = draw_puppet(d, display_height=300, right_hand=(460, 520), prop=prop).tobytes()
    assert with_prop != draw_puppet(d, display_height=300, right_hand=(460, 520)).tobytes()


def test_accessoires_et_chapeaux():
    base = draw_puppet(PuppetDesign(hat="none"), display_height=300).tobytes()
    for kw in ({"moustache": True}, {"glasses": True}, {"hat": "bowler"}, {"hat": "tophat"}, {"hat": "miner"}):
        assert draw_puppet(PuppetDesign(**{"hat": "none", **kw}), display_height=300).tobytes() != base, kw
    assert "mustache" in __import__("core.puppet", fromlist=["x"]).describe_design(PuppetDesign(moustache=True))

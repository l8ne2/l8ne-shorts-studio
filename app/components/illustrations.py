"""Section « Illustrations IA » d'un projet (styles non « stock »)."""
import json
from pathlib import Path

import streamlit as st

from core import dialogue as dlg_mod
from core import illustrator
from core.pipeline import load_segments
from core.image_generator import ImageGenerationError
from core.looks import resolve_look
from core.puppet import PuppetDesign, describe_design
from core.scene_planner import plan_dialogue_scenes, plan_scenes
from core.styles import EMOTION_LABELS, EMOTIONS, PUPPET_EMOTIONS, get_style
from core.visual_finder import split_scenes
from database.db import get_character, list_expressions, replace_asset, set_status


SCENE_TYPES = {"puppet": "Marionnette devant décor", "illustration": "Illustration complète"}


def render_illustrations(project, script: str, cfg: dict) -> None:
    pid = project["id"]
    style_key = project["style"]
    style = get_style(style_key)
    character = get_character(project["character_id"]) if project["character_id"] else None
    expressions = list_expressions(character["id"]) if character else {}
    sprite_mode = style["composition"] == "sprite"
    puppet_mode = style["composition"] == "puppet"
    emotion_mode = sprite_mode or puppet_mode
    if puppet_mode and not character:
        st.warning("Ce style a besoin d'un personnage : crée-le dans le « Studio personnages » puis recrée le projet.")
        return

    look = resolve_look(project.get("look"), cfg)
    dlg = dlg_mod.load_config(pid) if puppet_mode else None          # projet en dialogue ? (2 personnages)
    speaker_chars = [get_character(sp["character_id"]) for sp in dlg["speakers"]] if dlg else []
    if dlg and (len(speaker_chars) < 2 or any(c is None for c in speaker_chars)):
        st.warning("Un des personnages du dialogue est introuvable : recrée le projet avec deux personnages.")
        return
    st.caption(f"Style : {style['label']} · Ambiance : {look['label']}" + (f" · Personnage : {character['name']}" if character and not dlg else "")
               + (f" · Dialogue : {' et '.join(c['name'] for c in speaker_chars)}" if dlg else ""))
    if sprite_mode and not any(Path(p).exists() for p in expressions.values()):
        st.warning("Ce style utilise un personnage découpé : crée ses expressions dans le « Studio personnages ».")
        return

    plan_key, img_key = f"plan_{pid}", f"imgs_{pid}"
    if st.button("🧩 Préparer les scènes"):
        segments = load_segments(pid) if dlg else None
        if dlg and not segments:
            st.error("Génère d'abord la voix du dialogue (étape 3) : les scènes suivent les répliques.")
            scenes = []
        elif dlg:
            scenes = dlg_mod.group_segments(segments)
        else:
            scenes = split_scenes(script)
            if not scenes:
                st.error("Le script est vide.")
        if scenes:
            with st.spinner("Découpage et plan visuel (Groq)..."):
                if dlg:
                    plans, fallback = plan_dialogue_scenes(scenes, project["topic"] or project["title"], dlg["speakers"])
                    plan_items = [{**sc, **p} for sc, p in zip(scenes, plans)]
                else:
                    plans, fallback = plan_scenes(
                        scenes, project["topic"] or project["title"], style_key,
                        character["description"] if character else None,
                    )
                    plan_items = [{"text": t, **p} for t, p in zip(scenes, plans)]
            st.session_state[plan_key] = plan_items
            st.session_state[img_key] = {}
            for i, p in enumerate(plans):  # (ré)initialise les champs modifiables
                st.session_state[f"visual_{pid}_{i}"] = p["visual"]
                if dlg:
                    for j in (0, 1):
                        st.session_state[f"emotion_{pid}_{i}_{j}"] = p["emotions"][j]
                else:
                    st.session_state[f"emotion_{pid}_{i}"] = p["emotion"]
                st.session_state[f"label_{pid}_{i}"] = p["label"]
                st.session_state[f"type_{pid}_{i}"] = p.get("type", "puppet")
            if fallback:
                st.warning("Plan automatique indisponible : le sujet a été utilisé comme description. Modifie-les à la main.")

    plan = st.session_state.get(plan_key)
    if not plan:
        return
    images = st.session_state.setdefault(img_key, {})

    def scene_type(i: int) -> str:
        return st.session_state.get(f"type_{pid}_{i}", "puppet") if puppet_mode else "puppet"

    def generate(i: int, attempt: int = 0) -> bool:
        full = puppet_mode and scene_type(i) == "illustration"
        if full and dlg:  # les deux personnages sont dessinés dans l'image
            description = ("two characters side by side: first, "
                           + describe_design(PuppetDesign.from_json(speaker_chars[0]["description"]))
                           + "; second, " + describe_design(PuppetDesign.from_json(speaker_chars[1]["description"])))
        elif full:  # le personnage est dessiné dans l'image : on décrit sa tenue à l'IA
            description = describe_design(PuppetDesign.from_json(character["description"]))
        else:
            description = character["description"] if character and not (sprite_mode or puppet_mode) else None
        try:
            images[i] = {
                "path": str(illustrator.generate_scene_image(
                    pid, i, st.session_state[f"visual_{pid}_{i}"], style_key, description, attempt=attempt,
                    look_prefix=look["bg_prefix"], full_scene=full)),
                "attempt": attempt, "type": scene_type(i),
            }
            return True
        except ImageGenerationError as exc:
            set_status(pid, project["status"], error=str(exc))
            st.error(str(exc))
            return False

    st.markdown("**Scènes** — modifie les descriptions (en anglais) avant de générer.")
    for i, scene in enumerate(plan):
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"**Scène {i + 1}** — {scene['text']}")
            st.text_area("Description du décor (anglais)", key=f"visual_{pid}_{i}", height=70)
            if puppet_mode:
                st.selectbox("Type de scène", list(SCENE_TYPES), key=f"type_{pid}_{i}",
                             format_func=lambda t: SCENE_TYPES[t])
            if dlg:
                if scene_type(i) == "puppet":
                    for j, col in enumerate(st.columns(2)):
                        col.selectbox(f"Expression de {speaker_chars[j]['name']}", PUPPET_EMOTIONS,
                                      key=f"emotion_{pid}_{i}_{j}", format_func=lambda e: EMOTION_LABELS[e])
                st.text_input("Texte à l'écran (facultatif)", key=f"label_{pid}_{i}")
            else:
                c1, c2 = st.columns(2)
                if emotion_mode and scene_type(i) == "puppet":
                    c1.selectbox("Expression", PUPPET_EMOTIONS if puppet_mode else EMOTIONS, key=f"emotion_{pid}_{i}",
                                 format_func=lambda e: EMOTION_LABELS[e])
                c2.text_input("Texte à l'écran (facultatif)", key=f"label_{pid}_{i}")
            if i in images and images[i].get("type") != scene_type(i):
                st.caption("⚠️ Type de scène modifié : clique sur « Autre variante » pour régénérer l'image.")
            if i in images and st.button("🔄 Autre variante", key=f"regen_{pid}_{i}"):
                with st.spinner("Nouvelle variante..."):
                    generate(i, images[i]["attempt"] + 1)
        with right:
            if i in images:
                st.image(images[i]["path"])

    if st.button("🎨 Générer les images manquantes"):
        todo = [i for i in range(len(plan)) if i not in images or images[i].get("type") != scene_type(i)]
        bar = st.progress(0.0, text="Génération...")
        for n, i in enumerate(todo, 1):
            if not generate(i):
                break
            bar.progress(n / len(todo), text=f"Image {n}/{len(todo)}")
        st.rerun()

    ready = all(i in images and images[i].get("type") == scene_type(i) for i in range(len(plan)))
    if ready and st.button("✅ Valider les illustrations"):
        entries = []
        for i, scene in enumerate(plan):
            current = {"visual": st.session_state[f"visual_{pid}_{i}"],
                       "emotion": st.session_state.get(f"emotion_{pid}_{i}", "neutral"),
                       "label": st.session_state.get(f"label_{pid}_{i}", "")}
            sprite = illustrator.pick_sprite(expressions, current["emotion"]) if sprite_mode else None
            animation = None
            if dlg:
                emos = [st.session_state.get(f"emotion_{pid}_{i}_{j}", "neutral") for j in (0, 1)]
                current["emotion"] = emos[0]
                if scene_type(i) == "puppet":
                    animation = {"type": "dialogue", "characters": [
                        {"design": json.loads(c["description"] or "{}"), "emotion": e}
                        for c, e in zip(speaker_chars, emos)]}
            elif puppet_mode and scene_type(i) == "puppet":
                animation = {"type": "puppet", "design": json.loads(character["description"] or "{}")}
            elif sprite:
                animation = {"type": "sprite"}
            entries.append(illustrator.build_entry(i, scene["text"], current, images[i]["path"], sprite,
                                                   images[i]["attempt"], animation,
                                                   segments=scene.get("segments") if dlg else None))
        plan_path = illustrator.save_plan(entries, illustrator.IMAGES_DIR / f"project_{pid}" / "scenes.json")
        replace_asset(pid, "scenes", plan_path, source="flux-schnell")
        set_status(pid, "ASSETS_READY")
        st.success("Illustrations enregistrées. Statut : ASSETS_READY")
        st.caption(illustrator.CREDIT)

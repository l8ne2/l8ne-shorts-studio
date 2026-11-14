"""Section « Illustrations IA » d'un projet (styles non « stock »)."""
import json
from pathlib import Path

import streamlit as st

from core import illustrator
from core.image_generator import ImageGenerationError
from core.scene_planner import plan_scenes
from core.styles import EMOTION_LABELS, EMOTIONS, get_style
from core.visual_finder import split_scenes
from database.db import get_character, list_expressions, replace_asset, set_status


def render_illustrations(project, script: str) -> None:
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

    st.caption(f"Style : {style['label']}" + (f" · Personnage : {character['name']}" if character else ""))
    if sprite_mode and not any(Path(p).exists() for p in expressions.values()):
        st.warning("Ce style utilise un personnage découpé : crée ses expressions dans le « Studio personnages ».")
        return

    plan_key, img_key = f"plan_{pid}", f"imgs_{pid}"
    if st.button("🧩 Préparer les scènes"):
        scenes = split_scenes(script)
        if not scenes:
            st.error("Le script est vide.")
        else:
            with st.spinner("Découpage et plan visuel (Groq)..."):
                plans, fallback = plan_scenes(
                    scenes, project["topic"] or project["title"], style_key,
                    character["description"] if character else None,
                )
            st.session_state[plan_key] = [{"text": t, **p} for t, p in zip(scenes, plans)]
            st.session_state[img_key] = {}
            for i, p in enumerate(plans):  # (ré)initialise les champs modifiables
                st.session_state[f"visual_{pid}_{i}"] = p["visual"]
                st.session_state[f"emotion_{pid}_{i}"] = p["emotion"]
                st.session_state[f"label_{pid}_{i}"] = p["label"]
            if fallback:
                st.warning("Plan automatique indisponible : le sujet a été utilisé comme description. Modifie-les à la main.")

    plan = st.session_state.get(plan_key)
    if not plan:
        return
    images = st.session_state.setdefault(img_key, {})

    def generate(i: int, attempt: int = 0) -> bool:
        try:
            images[i] = {
                "path": str(illustrator.generate_scene_image(
                    pid, i, st.session_state[f"visual_{pid}_{i}"], style_key,
                    character["description"] if character and not (sprite_mode or puppet_mode) else None, attempt=attempt)),
                "attempt": attempt,
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
            c1, c2 = st.columns(2)
            if emotion_mode:
                c1.selectbox("Expression", EMOTIONS, key=f"emotion_{pid}_{i}",
                             format_func=lambda e: EMOTION_LABELS[e])
            if style["labels"]:
                c2.text_input("Étiquette à l'écran", key=f"label_{pid}_{i}")
            if i in images and st.button("🔄 Autre variante", key=f"regen_{pid}_{i}"):
                with st.spinner("Nouvelle variante..."):
                    generate(i, images[i]["attempt"] + 1)
        with right:
            if i in images:
                st.image(images[i]["path"])

    if st.button("🎨 Générer les images manquantes"):
        todo = [i for i in range(len(plan)) if i not in images]
        bar = st.progress(0.0, text="Génération...")
        for n, i in enumerate(todo, 1):
            if not generate(i):
                break
            bar.progress(n / len(todo), text=f"Image {n}/{len(todo)}")
        st.rerun()

    if len(images) == len(plan) and st.button("✅ Valider les illustrations"):
        entries = []
        for i, scene in enumerate(plan):
            current = {"visual": st.session_state[f"visual_{pid}_{i}"],
                       "emotion": st.session_state.get(f"emotion_{pid}_{i}", "neutral"),
                       "label": st.session_state.get(f"label_{pid}_{i}", "") if style["labels"] else ""}
            sprite = illustrator.pick_sprite(expressions, current["emotion"]) if sprite_mode else None
            animation = None
            if puppet_mode:
                animation = {"type": "puppet", "design": json.loads(character["description"] or "{}")}
            elif sprite:
                animation = {"type": "sprite"}
            entries.append(illustrator.build_entry(i, scene["text"], current, images[i]["path"], sprite,
                                                   images[i]["attempt"], animation))
        plan_path = illustrator.save_plan(entries, illustrator.IMAGES_DIR / f"project_{pid}" / "scenes.json")
        replace_asset(pid, "scenes", plan_path, source="flux-schnell")
        set_status(pid, "ASSETS_READY")
        st.success("Illustrations enregistrées. Statut : ASSETS_READY")
        st.caption(illustrator.CREDIT)

from pathlib import Path

import streamlit as st

from core import character_studio, illustrator
from core.character_studio import CutoutError
from core.config import ROOT
from core.puppet import BODIES, HATS, PRESETS, PuppetDesign, draw_puppet
from core.image_generator import ImageGenerationError, generate_image
from core.styles import EMOTION_LABELS, PUPPET_EMOTIONS, EMOTIONS, STYLES, get_style
from database.db import (
    create_character, get_character, list_characters, list_expressions, set_expression, update_character,
)

st.title("🎭 Studio personnages")
st.caption("Crée un personnage une seule fois, puis réutilise-le dans toutes tes vidéos.")

CHARACTER_STYLES = [k for k, v in STYLES.items() if v["characters"]]

with st.expander("➕ Nouveau personnage", expanded=not list_characters()):
    style_key = st.selectbox("Style", CHARACTER_STYLES, format_func=lambda k: STYLES[k]["label"], key="new_char_style")
    is_puppet = STYLES[style_key]["composition"] == "puppet"
    with st.form("new_character"):
        name = st.text_input("Nom")
        description = "" if is_puppet else st.text_area(
            "Description (en anglais, précise : couleurs, vêtements, traits)", height=90,
            placeholder="a small round robot explorer with a yellow helmet, big blue eyes, orange scarf",
        )
        if is_puppet:
            st.caption("Tu dessineras le personnage (couleurs, chapeau...) juste après la création.")
        if st.form_submit_button("Créer"):
            if not name.strip() or (not is_puppet and not description.strip()):
                st.error("Le nom et la description sont obligatoires.")
            else:
                st.session_state["studio_character"] = create_character(
                    name.strip(), style_key, PuppetDesign().to_json() if is_puppet else description.strip())
                st.rerun()

characters = list_characters()
if not characters:
    st.stop()

ids = [c["id"] for c in characters]
current = st.session_state.get("studio_character", ids[0])
selected_id = st.selectbox(
    "Personnage", ids, index=ids.index(current) if current in ids else 0,
    format_func=lambda i: next(f"{c['name']} — {get_style(c['style'])['label']}" for c in characters if c["id"] == i),
)
st.session_state["studio_character"] = selected_id
character = get_character(selected_id)
style = get_style(character["style"])
char_dir = ROOT / "media" / "characters" / str(selected_id)

if style["composition"] == "puppet":
    design = PuppetDesign.from_json(character["description"])
    k = f"_{selected_id}"
    BODY_LABELS = {"dressed": "Habillé (soldat, uniforme...)", "stick": "Bonhomme bâton", "cozy": "Petit pull mignon"}

    def apply_preset(name: str) -> None:
        """Remplit les champs ci-dessous avec un modèle (exécuté avant l'affichage des champs)."""
        d = PRESETS[name][1]
        values = {"body": d.body, "skin": d.skin, "outfit": d.outfit, "pants": d.pants, "hatc": d.hat_color,
                  "hair": d.hair, "hat": d.hat, "belt": d.belt, "outline": d.outline, "lines": d.line_scale,
                  "shade": d.shading, "blush": d.blush}
        for key, value in values.items():
            st.session_state[key + k] = value

    st.subheader("Dessine ton personnage")
    st.caption("Modèles de départ (tu peux ensuite tout modifier) :")
    for col, (name, (label, _)) in zip(st.columns(len(PRESETS)), PRESETS.items()):
        col.button(label, key=f"preset_{name}{k}", on_click=apply_preset, args=(name,))
    name_in = st.text_input("Nom", character["name"], key="pname" + k)
    # valeurs de départ posées une seule fois dans l'état de la page (les modèles peuvent ensuite les remplacer)
    for key, value in {"body": design.body, "skin": design.skin, "outfit": design.outfit, "pants": design.pants,
                       "hatc": design.hat_color, "hair": design.hair, "outline": design.outline, "hat": design.hat,
                       "belt": design.belt, "shade": design.shading, "blush": design.blush,
                       "lines": float(design.line_scale)}.items():
        st.session_state.setdefault(key + k, value)
    body = st.selectbox("Corps", BODIES, format_func=lambda b: BODY_LABELS[b], key="body" + k)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    skin = c1.color_picker("Tête / peau", key="skin" + k)
    outfit = c2.color_picker("Haut", key="outfit" + k)
    pants = c3.color_picker("Pantalon", key="pants" + k)
    hat_color = c4.color_picker("Chapeau", key="hatc" + k)
    hair = c5.color_picker("Cheveux", key="hair" + k)
    outline = c6.color_picker("Contour", key="outline" + k)
    h1, h2, h3, h4, h5 = st.columns(5)
    hat = h1.selectbox("Coiffure / chapeau", HATS,
                       format_func=lambda x: {"none": "Aucun", "cap": "Casquette", "beanie": "Bonnet",
                                              "helmet": "Casque", "hair": "Cheveux"}[x], key="hat" + k)
    belt = h2.checkbox("Ceinture (habillé)", key="belt" + k)
    shading = h3.checkbox("Ombrage doux", key="shade" + k)
    blush = h4.checkbox("Joues roses", key="blush" + k)
    lines = h5.slider("Épaisseur du trait", 0.6, 1.8, step=0.05, key="lines" + k)
    new_design = PuppetDesign(skin=skin, outfit=outfit, pants=pants, hat=hat, hat_color=hat_color, hair=hair,
                              belt=belt, body=body, outline=outline, line_scale=lines, shading=shading, blush=blush)
    st.caption("Aperçu des expressions (la bouche s'ouvrira au rythme de la voix dans la vidéo) :")
    shots = [(draw_puppet(new_design, e, display_height=260), EMOTION_LABELS[e]) for e in PUPPET_EMOTIONS]
    shots.append((draw_puppet(new_design, "happy", mouth=2, arm_raise=1.0, display_height=260), "Parle"))
    for col, (img, label) in zip(st.columns(len(shots)), shots):
        col.image(img, caption=label)
    if st.button("💾 Enregistrer le personnage"):
        update_character(selected_id, name_in.strip() or character["name"], new_design.to_json())
        st.success("Personnage enregistré.")
    st.stop()

with st.form("edit_character"):
    new_name = st.text_input("Nom", character["name"])
    new_desc = st.text_area("Description (anglais)", character["description"], height=90)
    if st.form_submit_button("Enregistrer les modifications"):
        update_character(selected_id, new_name.strip() or character["name"], new_desc.strip() or character["description"])
        st.rerun()

if style["composition"] != "sprite":
    st.info("Ce style dessine le personnage directement dans chaque scène : pas d'expressions à préparer. "
            "Teste son apparence avec un aperçu.")
    if st.button("🖼️ Générer un aperçu"):
        try:
            with st.spinner("Génération..."):
                path = illustrator.generate_scene_image(
                    0, 0, "the character in a sunny village street, full body", character["style"],
                    character["description"], out_dir=char_dir / "preview", attempt=len(list(char_dir.glob("preview/*"))))
            st.image(str(path), width=300)
        except ImageGenerationError as exc:
            st.error(str(exc))
    st.stop()

# --- Style « sprite » : expressions ------------------------------------------------------------
st.subheader("Expressions")
expressions = {e: p for e, p in list_expressions(selected_id).items() if Path(p).exists()}
if expressions:
    cols = st.columns(len(EMOTIONS))
    for col, emotion in zip(cols, EMOTIONS):
        with col:
            if emotion in expressions:
                col.image(expressions[emotion])
            col.caption(EMOTION_LABELS[emotion] + (" ✅" if emotion in expressions else " —"))

picked = st.multiselect("Expressions à générer", EMOTIONS, default=[e for e in EMOTIONS if e not in expressions],
                        format_func=lambda e: EMOTION_LABELS[e])
st.caption(f"{len(picked) * 2} images seront générées (2 variantes par expression) sur ton quota gratuit Cloudflare.")
cand_key = f"candidates_{selected_id}"
if st.button("🎨 Générer les variantes") and picked:
    total = len(picked) * 2
    bar = st.progress(0.0, text="Génération...")
    done = {"n": 0}

    def tracked(prompt, seed=None, **kw):
        data = generate_image(prompt, seed=seed, **kw)
        done["n"] += 1
        bar.progress(done["n"] / total, text=f"Image {done['n']}/{total}")
        return data

    try:
        st.session_state[cand_key] = character_studio.generate_candidates(
            selected_id, character["style"], character["description"], char_dir / "candidates",
            emotions=picked, per_emotion=2, generator=tracked,
        )
    except ImageGenerationError as exc:
        st.error(str(exc))

cands = st.session_state.get(cand_key)
if cands:
    st.markdown("**Choisis la meilleure variante de chaque expression** (ou aucune).")
    choices = {}
    for emotion, paths in cands.items():
        st.markdown(f"**{EMOTION_LABELS[emotion]}**")
        cols = st.columns(len(paths))
        for col, p in zip(cols, paths):
            col.image(str(p), width=220)
        choices[emotion] = st.radio(
            "Choix", [None, *range(len(paths))], horizontal=True, key=f"pick_{selected_id}_{emotion}",
            format_func=lambda j: "Aucune" if j is None else f"Variante {j + 1}", label_visibility="collapsed",
        )
    if st.button("✂️ Créer les personnages découpés"):
        made, errors = 0, []
        with st.spinner("Retrait du fond..."):
            for emotion, j in choices.items():
                if j is None:
                    continue
                try:
                    sprite = character_studio.make_sprite(cands[emotion][j], char_dir / f"{emotion}.png")
                    set_expression(selected_id, emotion, sprite)
                    made += 1
                except CutoutError as exc:
                    errors.append(f"{EMOTION_LABELS[emotion]} : {exc}")
        for e in errors:
            st.error(e)
        if made:
            st.success(f"{made} expression(s) enregistrée(s).")
            st.rerun()

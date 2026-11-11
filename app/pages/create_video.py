import json

import streamlit as st

from database.db import create_project, get_project, list_channels, set_status, update_script

WORDS_PER_SECOND = 2.5  # débit approximatif de narration en français

st.title("✍️ Créer une vidéo")
channels = list_channels()
by_name = {c["name"]: c for c in channels}

st.subheader("1. Nouveau projet")
with st.form("new_project"):
    channel_name = st.selectbox("Chaîne", list(by_name))
    title = st.text_input("Titre du projet")
    topic = st.text_area("Sujet", height=80)
    submitted = st.form_submit_button("Créer le projet")
if submitted:
    if not title.strip():
        st.error("Donne un titre au projet.")
    else:
        st.session_state["project_id"] = create_project(
            by_name[channel_name]["id"], title.strip(), topic.strip()
        )
        st.success("Projet créé.")

project_id = st.session_state.get("project_id")
if project_id:
    project = get_project(project_id)
    cfg = json.loads(next(c["config"] for c in channels if c["id"] == project["channel_id"]))
    target_words = int(cfg["duration"] * WORDS_PER_SECOND)

    st.subheader(f"2. Script — {project['title']}")
    st.caption(
        f"Chaîne : {project['channel_name']} · Statut : {project['status']} · "
        f"Durée cible : {cfg['duration']} s (≈ {target_words} mots)"
    )
    script = st.text_area("Script", value=project["script"] or "", height=250)
    st.caption(f"{len(script.split())} mots")
    c1, c2 = st.columns(2)
    if c1.button("💾 Enregistrer"):
        update_script(project_id, script)
        st.success("Script enregistré.")
    if c2.button("✅ Valider le script"):
        if not script.strip():
            st.error("Le script est vide.")
        else:
            update_script(project_id, script)
            set_status(project_id, "SCRIPT_READY")
            st.success("Statut : SCRIPT_READY")
    st.info("La génération automatique du script (Groq) arrive en Phase 2.")

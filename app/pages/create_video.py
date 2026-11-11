import json

import streamlit as st

from core.script_generator import ScriptGenerationError, check_script, generate_script, target_words
from core.voice_generator import VoiceGenerationError, generate_voice
from database.db import (
    create_project, get_project, list_assets, list_channels, replace_asset, set_status, update_script,
)

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
    key = f"script_{project_id}"
    if key not in st.session_state:
        st.session_state[key] = project["script"] or ""

    def on_generate():
        """Callback : s'exécute avant le rendu, donc peut modifier la zone de texte."""
        current = get_project(project_id)
        try:
            script = generate_script(current["topic"] or current["title"], cfg)
        except ScriptGenerationError as exc:
            set_status(project_id, current["status"], error=str(exc))
            return
        st.session_state[key] = script
        update_script(project_id, script)
        set_status(project_id, current["status"], error=None)

    st.subheader(f"2. Script — {project['title']}")
    st.caption(
        f"Chaîne : {project['channel_name']} · Statut : {project['status']} · "
        f"Durée cible : {cfg['duration']} s (≈ {target_words(cfg['duration'])} mots)"
    )
    if project["error"]:
        st.error(project["error"])

    st.button("🤖 Générer avec Groq", on_click=on_generate)
    script = st.text_area("Script (modifiable)", key=key, height=250)
    st.caption(f"{len(script.split())} mots")
    for w in check_script(script, cfg["duration"]) if script.strip() else []:
        st.warning(w)

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

    st.subheader("3. Voix off")
    voice_name = cfg.get("voice", {}).get("name", "voix par défaut")
    st.caption(f"Voix : {voice_name}. Le script enregistré est utilisé pour générer l'audio.")
    if st.button("🎙️ Générer la voix"):
        if not script.strip():
            st.error("Écris ou génère d'abord un script.")
        else:
            update_script(project_id, script)
            try:
                with st.spinner("Génération de la voix..."):
                    result = generate_voice(script, cfg, project_id)
            except VoiceGenerationError as exc:
                set_status(project_id, project["status"], error=str(exc))
                st.error(str(exc))
            else:
                replace_asset(project_id, "audio", result["audio_path"], source="edge-tts")
                replace_asset(project_id, "timings", result["words_path"], source="edge-tts")
                set_status(project_id, "AUDIO_READY")
                st.success(f"Voix générée ({result['duration'] or '?'} s). Statut : AUDIO_READY")

    audio_assets = list_assets(project_id, "audio")
    if audio_assets:
        st.audio(audio_assets[-1]["file_path"])

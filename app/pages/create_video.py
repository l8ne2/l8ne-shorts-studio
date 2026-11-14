import json
from pathlib import Path

import streamlit as st

from core.script_generator import ScriptGenerationError, check_script, generate_script, target_words
from app.components.illustrations import render_illustrations
from core.pipeline import missing_steps, render_project
from core.styles import STYLES
from core.subtitle_generator import SubtitleError, generate_subtitles
from core.visual_finder import (
    VIDEOS_DIR, VisualSearchError, build_credits, credit_line, download_video,
    plan_queries, search_videos, split_scenes,
)
from core.video_editor import FRAMINGS, VideoEditError
from core.voice_generator import VoiceGenerationError, generate_voice
from database.db import (
    create_project, get_project, list_characters, list_assets, list_channels, list_exports, replace_asset, replace_assets,
    set_status, update_script,
)

st.title("✍️ Créer une vidéo")
channels = list_channels()
by_name = {c["name"]: c for c in channels}

st.subheader("1. Nouveau projet")
style_key = st.selectbox("Style de la vidéo", list(STYLES), format_func=lambda k: STYLES[k]["label"])
st.caption(STYLES[style_key]["description"])
character = None
if STYLES[style_key]["characters"]:
    available = list_characters(style_key)
    if not available:
        st.info("Aucun personnage pour ce style : crée-en un dans le « Studio personnages ».")
    character = st.selectbox("Personnage", [None, *available],
                             format_func=lambda c: "Aucun" if c is None else c["name"])
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
            by_name[channel_name]["id"], title.strip(), topic.strip(),
            style=style_key, character_id=character["id"] if character else None,
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

    audio_assets = [a for a in list_assets(project_id, "audio") if Path(a["file_path"]).exists()]
    if audio_assets:
        st.audio(audio_assets[-1]["file_path"])

    st.subheader("4. Visuels")
    if project["style"] == "stock":
        if not audio_assets:
            st.info("Génère d'abord la voix off pour passer aux visuels.")
        else:
            scenes_key = f"scenes_{project_id}"
            if st.button("🔎 Chercher des visuels"):
                scenes = split_scenes(script)
                if not scenes:
                    st.error("Le script est vide.")
                else:
                    try:
                        with st.spinner("Recherche des visuels..."):
                            queries, fallback = plan_queries(scenes, project["topic"] or project["title"])
                            st.session_state[scenes_key] = [
                                {"text": t, "query": q, "candidates": search_videos(q)}
                                for t, q in zip(scenes, queries)
                            ]
                        if fallback:
                            st.warning("Requêtes automatiques indisponibles : le sujet a été utilisé comme requête.")
                    except VisualSearchError as exc:
                        set_status(project_id, project["status"], error=str(exc))
                        st.error(str(exc))

            found = st.session_state.get(scenes_key)
            if found:
                choices = {}
                for i, scene in enumerate(found):
                    st.markdown(f"**Scène {i + 1}** — {scene['text']}")
                    st.caption(f"Requête : {scene['query']}")
                    cands = scene["candidates"]
                    if not cands:
                        st.warning("Aucun résultat pour cette scène.")
                        continue
                    cols = st.columns(len(cands))
                    for j, (col, c) in enumerate(zip(cols, cands)):
                        if c["preview"]:
                            col.image(c["preview"], caption=f"Option {j + 1} · {c['duration']} s")
                        else:
                            col.write(f"Option {j + 1} · {c['duration']} s (pas d'aperçu)")
                        if c.get("page_url"):
                            col.caption(f"[Voir la vidéo]({c['page_url']})")
                    choices[i] = st.radio(
                        "Choix", range(len(cands)), format_func=lambda j: f"Option {j + 1}",
                        horizontal=True, key=f"choice_{project_id}_{i}", label_visibility="collapsed",
                    )
                if st.button("✅ Valider et télécharger les visuels") and choices:
                    try:
                        with st.spinner("Téléchargement des clips..."):
                            folder = VIDEOS_DIR / f"project_{project_id}"
                            items, plan, picked = [], [], []
                            for i, j in choices.items():
                                cand = found[i]["candidates"][j]
                                path = download_video(cand, folder / f"scene_{i + 1}.mp4")
                                items.append((path, credit_line(cand)))
                                picked.append(cand)
                                plan.append({"scene": i + 1, "text": found[i]["text"], "query": found[i]["query"],
                                             "file": str(path), "duration": cand["duration"],
                                             "credit": credit_line(cand)})
                            plan_path = folder / "scenes.json"
                            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
                        replace_assets(project_id, "video_clip", items)
                        replace_asset(project_id, "scenes", plan_path, source=picked[0].get("provider", "pexels") if picked else "stock")
                        set_status(project_id, "ASSETS_READY")
                        st.success("Visuels enregistrés. Statut : ASSETS_READY")
                        st.text_area("Crédits à coller dans la description YouTube", build_credits(picked), height=100)
                    except VisualSearchError as exc:
                        set_status(project_id, project["status"], error=str(exc))
                        st.error(str(exc))
    elif not audio_assets:
        st.info("Génère d'abord la voix off pour passer aux visuels.")
    else:
        render_illustrations(project, script)

    st.subheader("5. Sous-titres")
    timing_assets = [a for a in list_assets(project_id, "timings") if Path(a["file_path"]).exists()]
    if not timing_assets:
        st.info("Les sous-titres sont synchronisés sur la voix : génère d'abord la voix off.")
    else:
        style_name = cfg.get("style", {}).get("subtitles", "modernes")
        st.caption(f"Style de la chaîne : {style_name}. Synchronisés mot par mot sur la voix.")
        if st.button("💬 Générer les sous-titres"):
            try:
                result = generate_subtitles(timing_assets[-1]["file_path"], cfg)
            except SubtitleError as exc:
                set_status(project_id, project["status"], error=str(exc))
                st.error(str(exc))
            else:
                replace_asset(project_id, "subtitles_srt", result["srt_path"], source="edge-tts")
                replace_asset(project_id, "subtitles_ass", result["ass_path"], source="edge-tts")
                st.success(f"{len(result['cues'])} sous-titres générés.")
        srt_assets = [a for a in list_assets(project_id, "subtitles_srt") if Path(a["file_path"]).exists()]
        if srt_assets:
            srt_text = Path(srt_assets[-1]["file_path"]).read_text(encoding="utf-8")
            st.text_area("Aperçu (.srt)", srt_text, height=160, disabled=True)
            st.download_button("⬇️ Télécharger le .srt", srt_text, file_name=f"project_{project_id}.srt")

    st.subheader("6. Montage et export")
    todo = missing_steps(project_id)
    if todo:
        st.info("Avant le montage, termine : " + ", ".join(dict.fromkeys(todo)) + ".")
    else:
        default_framing = cfg.get("framing", "crop")
        framing = st.radio(
            "Cadrage des vidéos", FRAMINGS, index=FRAMINGS.index(default_framing),
            format_func=lambda f: "Plein écran recadré (recommandé)" if f == "crop" else "Vidéo entière sur fond flou",
            horizontal=True,
        )
        if st.button("🎬 Monter la vidéo"):
            try:
                with st.spinner("Montage en cours (quelques minutes selon ton PC)..."):
                    result = render_project(project_id, framing=framing)
            except VideoEditError as exc:
                st.error(str(exc))
            else:
                st.success(f"Vidéo exportée ({result['duration']:.0f} s). Statut : COMPLETED")
                st.session_state[f"credits_{project_id}"] = result["credits"]
        exports = [e for e in list_exports(project_id) if Path(e["file_path"]).exists()]
        if exports:
            st.video(exports[0]["file_path"])
            st.caption(f"Fichier : {exports[0]['file_path']}")
            with open(exports[0]["file_path"], "rb") as f:
                st.download_button("⬇️ Télécharger le MP4", f, file_name=Path(exports[0]["file_path"]).name,
                                   mime="video/mp4")
            if st.session_state.get(f"credits_{project_id}"):
                st.text_area("Crédits à coller dans la description YouTube",
                             st.session_state[f"credits_{project_id}"], height=100)
            st.warning("Vérifie les faits, les droits des médias, la narration et le montage avant de publier.")

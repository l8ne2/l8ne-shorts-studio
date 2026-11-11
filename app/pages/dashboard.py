import streamlit as st

from database.db import list_channels, list_projects

st.title("📊 Dashboard")

channels = list_channels()
cols = st.columns(len(channels))
for col, ch in zip(cols, channels):
    nb = len(list_projects(channel_id=ch["id"]))
    with col:
        st.metric(ch["name"], f"{nb} projet(s)")
        st.caption(ch["niche"])

st.subheader("Projets récents")
recent = list_projects(limit=10)
if not recent:
    st.info("Aucun projet pour l'instant. Va dans « Créer une vidéo » pour commencer.")
else:
    st.dataframe(
        [
            {
                "Titre": p["title"],
                "Chaîne": p["channel_name"],
                "Statut": p["status"],
                "Modifié": p["updated_at"],
            }
            for p in recent
        ],
        use_container_width=True,
        hide_index=True,
    )

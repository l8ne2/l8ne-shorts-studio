import streamlit as st

from database.db import STATUSES, list_channels, list_projects

st.title("🗂️ Projets")

channels = list_channels()
c1, c2 = st.columns(2)
channel = c1.selectbox("Chaîne", [None] + list(channels), format_func=lambda c: "Toutes" if c is None else c["name"])
status = c2.selectbox("Statut", [None] + STATUSES, format_func=lambda s: "Tous" if s is None else s)

projects = list_projects(channel_id=channel["id"] if channel else None, status=status)
if not projects:
    st.info("Aucun projet.")
for p in projects:
    with st.expander(f"#{p['id']} — {p['title']} · {p['channel_name']} · {p['status']}"):
        st.write(f"**Sujet :** {p['topic'] or '—'}")
        st.write(f"**Créé :** {p['created_at']}  |  **Modifié :** {p['updated_at']}")
        if p["error"]:
            st.error(p["error"])
        st.text_area("Script", p["script"] or "", height=150, disabled=True, key=f"s{p['id']}")

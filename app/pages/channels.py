import json

import streamlit as st

from database.db import list_channels

st.title("📺 Chaînes")
st.caption("Les paramètres viennent des fichiers YAML du dossier channels/.")

for ch in list_channels():
    cfg = json.loads(ch["config"])
    with st.expander(f"{ch['name']} — {cfg['language'].upper()} · {cfg['duration']} s · {cfg['format']}"):
        st.write(f"**Niche :** {cfg.get('niche', '—')}")
        style = cfg.get("style", {})
        st.write(
            f"**Ton :** {style.get('tone', '—')}  |  **Narration :** {style.get('narration', '—')}  |  "
            f"**Sous-titres :** {style.get('subtitles', '—')}"
        )
        st.write("**Types de contenu :** " + ", ".join(cfg.get("content", [])))

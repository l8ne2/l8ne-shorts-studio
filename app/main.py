"""Point d'entrée : streamlit run app/main.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from dotenv import load_dotenv

from app.components.sidebar import render_sidebar
from database.db import init_db

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="L8NE Shorts Studio", page_icon="🎬", layout="wide")
init_db()
render_sidebar()

pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("pages/channels.py", title="Chaînes", icon="📺"),
    st.Page("pages/studio.py", title="Studio personnages", icon="🎭"),
    st.Page("pages/create_video.py", title="Créer une vidéo", icon="✍️"),
    st.Page("pages/projects.py", title="Projets", icon="🗂️"),
    st.Page("pages/settings.py", title="Paramètres", icon="⚙️"),
]
st.navigation(pages).run()

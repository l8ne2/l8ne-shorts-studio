import os
import shutil

import streamlit as st

from core.config import ROOT
from database.db import DEFAULT_DB_PATH

st.title("⚙️ Paramètres")

st.subheader("Clés API (fichier .env)")
for key in ("GROQ_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "PIXABAY_API_KEY", "PEXELS_API_KEY"):
    st.write(("✅" if os.getenv(key) else "❌") + f" {key}")
st.caption("Visuels de stock : une clé parmi Pixabay et Pexels suffit. Illustrations IA : les deux clés Cloudflare. Copie .env.example en .env et renseigne tes clés. Le fichier .env n'est jamais envoyé sur GitHub.")

st.subheader("Outils")
ffmpeg = shutil.which("ffmpeg")
st.write(("✅ FFmpeg : " + ffmpeg) if ffmpeg else "❌ FFmpeg introuvable (à installer avant la Phase 3)")

st.subheader("Chemins")
st.code(f"Projet : {ROOT}\nBase   : {DEFAULT_DB_PATH}")

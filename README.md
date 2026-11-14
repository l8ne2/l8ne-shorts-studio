# L8NE Shorts Studio

Application locale pour produire des YouTube Shorts (MP4 vertical 1080×1920) pour trois chaînes depuis une seule interface :

- **Tech & IA**
- **Mystères & histoires**
- **Cinéma & séries**

Aucune vidéo n'est publiée automatiquement : tu vérifies les faits, les droits des médias, la narration et le montage avant publication.

## État du projet

- [x] Phase 1 — Fondations : dashboard Streamlit, configuration YAML des chaînes, base SQLite, statuts de projet
- [x] Phase 2 — Moteur de génération : Groq (scripts), Edge TTS (voix), Pixabay/Pexels (visuels de stock), sous-titres
- [x] Phase 3 — Montage FFmpeg, prévisualisation, export MP4
- [x] Styles animés : dessin animé 2D, personnage 3D coloré, explication 3D en coupe (images IA via Cloudflare Workers AI) et studio de personnages
- [ ] Tests sur les trois chaînes et version 1.0

## Installation (Windows)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Lancer l'application

```powershell
streamlit run app/main.py
```

## Lancer les tests

```powershell
pytest
```

## Structure

| Dossier | Rôle |
| --- | --- |
| `app/` | Interface Streamlit (pages et composants) |
| `core/` | Logique métier (config, pipeline, et plus tard IA, voix, visuels, montage) |
| `channels/` | Un fichier YAML par chaîne |
| `database/` | Accès SQLite (`studio.db` créé au premier lancement) |
| `media/`, `output/` | Fichiers intermédiaires et vidéos exportées (non versionnés) |
| `tests/` | Tests unitaires |

## Statuts d'un projet

`DRAFT → SCRIPT_READY → AUDIO_READY → ASSETS_READY → RENDERING → COMPLETED` (ou `ERROR`, le projet est conservé et on reprend à l'étape concernée).

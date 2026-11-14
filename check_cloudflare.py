"""Diagnostic des clés Cloudflare (Workers AI).

Usage (dans le dossier du projet, environnement virtuel activé) :
    python check_cloudflare.py

Le script ne montre jamais tes clés en entier. Il vérifie le format de l'Account ID et du jeton,
teste le jeton auprès de Cloudflare, puis génère une petite image de test.
"""
import os
import re
import sys

import requests
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))  # cherche .env dans le dossier où tu lances la commande
raw_account = os.getenv("CLOUDFLARE_ACCOUNT_ID") or ""
raw_token = os.getenv("CLOUDFLARE_API_TOKEN") or ""
account, token = raw_account.strip().strip("\"'"), raw_token.strip().strip("\"'")
problems = []

print("=== 1. Fichier .env ===")
if not raw_account:
    problems.append("CLOUDFLARE_ACCOUNT_ID est absent ou vide dans .env")
if not raw_token:
    problems.append("CLOUDFLARE_API_TOKEN est absent ou vide dans .env")
if raw_account != account or raw_token != token:
    problems.append("Il y a des espaces ou des guillemets autour d'une valeur dans .env : enlève-les "
                    "(écris CLOUDFLARE_API_TOKEN=abc..., sans guillemets ni espaces)")
if account:
    print(f"Account ID : {account[:4]}...{account[-4:]} ({len(account)} caractères)")
    if not re.fullmatch(r"[0-9a-f]{32}", account):
        problems.append("L'Account ID doit faire exactement 32 caractères (chiffres et lettres a-f). "
                        "Tu l'as peut-être confondu avec un autre identifiant (zone, token...)")
if token:
    print(f"Jeton      : {token[:4]}...{token[-4:]} ({len(token)} caractères)")
    if len(token) < 30 or len(token) > 60:
        problems.append("Longueur inhabituelle pour un jeton API (environ 40 caractères attendus). "
                        "Une « Global API Key » ne convient PAS : il faut un jeton API (API Token)")
if problems:
    print("\nProblèmes détectés :")
    for p in problems:
        print(" -", p)
if not account or not token:
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}"}
base = "https://api.cloudflare.com/client/v4"

print("\n=== 2. Test du jeton ===")
try:
    for label, url in (("jeton utilisateur", f"{base}/user/tokens/verify"),
                       ("jeton de compte", f"{base}/accounts/{account}/tokens/verify")):
        r = requests.get(url, headers=headers, timeout=20)
        ok = r.status_code == 200 and r.json().get("success")
        status = r.json().get("result", {}).get("status") if ok else None
        print(f"{label:18}: {'OK (' + str(status) + ')' if ok else 'refusé (HTTP ' + str(r.status_code) + ')'}")
        if ok:
            break
except Exception as exc:
    print("Connexion à Cloudflare impossible :", exc)
    sys.exit(1)

print("\n=== 3. Génération d'une image de test ===")
url = f"{base}/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell"
r = requests.post(url, headers=headers, json={"prompt": "a red circle on a white background", "steps": 4}, timeout=90)
print("Réponse HTTP :", r.status_code)
try:
    data = r.json()
except ValueError:
    data = {}
if r.status_code == 200 and (data.get("result") or {}).get("image"):
    print("OK : tout fonctionne. Relance Streamlit (Ctrl+C puis streamlit run app/main.py).")
    sys.exit(0)

for err in data.get("errors", []):
    print(f"Cloudflare : [{err.get('code')}] {err.get('message')}")
print("\nQue faire :")
if r.status_code in (401, 403):
    print(" - Crée un NOUVEAU jeton avec le modèle « Workers AI » : dash.cloudflare.com -> AI -> Workers AI ->")
    print("   « Utiliser l'API REST » -> « Créer un jeton d'API Workers AI ». Copie-le tout de suite (il ne")
    print("   s'affiche qu'une fois) et colle-le dans .env sans espace ni guillemets.")
    print(" - Vérifie que l'Account ID vient du MÊME compte Cloudflare que le jeton (même page « Workers AI »).")
    print(" - Si tu as ajouté des restrictions d'adresse IP au jeton, enlève-les.")
elif r.status_code == 429:
    print(" - Quota gratuit du jour atteint : réessaie demain.")
else:
    print(" - Erreur inattendue : envoie-moi le message ci-dessus (sans ta clé).")
sys.exit(1)

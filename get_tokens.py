"""
Run this ONCE locally to export your Garmin auth tokens.
These tokens get stored as GitHub Secrets so GitHub Actions
never needs to do a fresh Garmin login again.

Usage:
    python get_tokens.py

Then copy the output into two GitHub Secrets:
    GARTH_OAUTH1_TOKEN  ← paste the oauth1_token.json content
    GARTH_OAUTH2_TOKEN  ← paste the oauth2_token.json content
"""
import os, json
from garminconnect import Garmin
from dotenv import load_dotenv

TOKEN_DIR = "./garth_tokens_export"
os.makedirs(TOKEN_DIR, exist_ok=True)

load_dotenv()
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")

print("Logging in to Garmin Connect...")
garmin = Garmin(email, password)
garmin.login()
garmin.garth.dump(TOKEN_DIR)
print(f"Tokens saved to {TOKEN_DIR}/\n")

print("=" * 60)
print("Copy each block below into the matching GitHub Secret:")
print("=" * 60)

for fname in sorted(os.listdir(TOKEN_DIR)):
    fpath = os.path.join(TOKEN_DIR, fname)
    with open(fpath) as f:
        content = f.read().strip()
    secret_name = "GARTH_OAUTH1_TOKEN" if "oauth1" in fname else "GARTH_OAUTH2_TOKEN"
    print(f"\n--- GitHub Secret: {secret_name} ---")
    print(content)

print("\n" + "=" * 60)
print("Done. Add both secrets at:")
print("GitHub repo → Settings → Secrets and variables → Actions → New repository secret")

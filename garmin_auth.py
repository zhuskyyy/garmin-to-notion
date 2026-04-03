"""
Authenticate with Garmin once and save the token to /tmp/garth_tokens.
All other scripts load from this cache to avoid repeated logins (429 rate limits).

Strategy:
  1. Try loading cached token (restored from GitHub Actions cache between runs)
  2. Verify the token is still valid with a lightweight API call
  3. Only do a full fresh login if no valid cached token exists
  4. Always dump the token at the end so the cache is up to date
"""
import os
from garminconnect import Garmin
from dotenv import load_dotenv

TOKEN_DIR = "/tmp/garth_tokens"

load_dotenv()
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")

try:
    print("Attempting to load cached Garmin token...")
    garmin = Garmin()
    garmin.garth.load(TOKEN_DIR)
    garmin.get_full_name()  # lightweight call to verify token is valid
    print("Cached token is valid — no fresh login needed.")
except Exception as e:
    print(f"Cached token unavailable or expired ({e}) — performing fresh login...")
    garmin = Garmin(email, password)
    garmin.login()
    print("Fresh login successful.")

garmin.garth.dump(TOKEN_DIR)
print(f"Token saved to {TOKEN_DIR}")

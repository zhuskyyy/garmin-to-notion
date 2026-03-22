"""
Authenticate with Garmin once and save the token to /tmp/garth_tokens.
All other scripts load from this cache to avoid repeated logins (429 rate limits).
"""
import os
from garminconnect import Garmin
from dotenv import load_dotenv

TOKEN_DIR = "/tmp/garth_tokens"

load_dotenv()
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")

garmin = Garmin(email, password)
garmin.login()
garmin.garth.dump(TOKEN_DIR)
print(f"Garmin authenticated and token saved to {TOKEN_DIR}")

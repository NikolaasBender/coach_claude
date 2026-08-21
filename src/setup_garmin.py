"""One-time Garmin Connect login.

Logs in with your Garmin Connect credentials (MFA supported) and saves OAuth
tokens to GARMIN_TOKENS_PATH. Scheduled runs resume from those tokens — your
password is never stored. Tokens last ~1 year; re-run this when they expire.

Usage:
    python -m src.setup_garmin
"""

import os
import sys
from datetime import date, timedelta
from getpass import getpass

from dotenv import load_dotenv

load_dotenv()


def main():
    from garminconnect import Garmin, GarminConnectAuthenticationError

    tokens = os.environ.get("GARMIN_TOKENS_PATH", "data/garmin_tokens")

    print("\n--- Garmin Connect Login ---")
    email = os.environ.get("GARMIN_EMAIL", "").strip()
    if email:
        print(f"Using GARMIN_EMAIL from .env: {email}")
    else:
        email = input("Garmin Connect email: ").strip()
    password = getpass("Garmin Connect password (not stored): ")

    if not email or not password:
        print("Email and password are both required.")
        sys.exit(1)

    try:
        client = Garmin(
            email=email,
            password=password,
            prompt_mfa=lambda: input("MFA code (from your authenticator/email): ").strip(),
        )
        # On success this also dumps the OAuth tokens to `tokens` automatically.
        client.login(tokens)
    except GarminConnectAuthenticationError as e:
        print(f"\nLogin failed: {e}")
        print("Check email/password (and MFA code) and try again.")
        sys.exit(1)

    # Sanity check: prove the saved session can actually pull activities.
    end = date.today()
    start = end - timedelta(days=7)
    acts = client.get_activities_by_date(start.isoformat(), end.isoformat())

    print(f"\nLogged in OK — {len(acts)} activities found in the last 7 days.")
    print(f"Tokens saved to: {tokens}")
    print("In Docker, keep GARMIN_TOKENS_PATH on the mounted /data volume so the")
    print("cron runs can reuse this login.")


if __name__ == "__main__":
    main()

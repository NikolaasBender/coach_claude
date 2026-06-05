"""One-time Strava OAuth setup.

Run once to get your refresh_token, then add it to .env.
After that, coach_claude handles token refresh automatically.

Usage:
    python -m src.setup_strava
"""

import os
import sys
import webbrowser

import requests
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"

REQUIRED_SCOPE = "activity:read"


def main():
    client_id = os.environ.get("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print(
            "Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in your .env first.\n"
            "Register a free app at: https://www.strava.com/settings/api\n"
            "  - App Name: anything (e.g. 'coach_claude')\n"
            "  - Website: http://localhost\n"
            "  - Authorization Callback Domain: localhost\n"
            "Then copy the Client ID and Client Secret into .env."
        )
        sys.exit(1)

    auth_url = (
        f"{AUTH_URL}?client_id={client_id}"
        f"&redirect_uri=http://localhost"
        f"&response_type=code"
        f"&approval_prompt=force"
        f"&scope={REQUIRED_SCOPE}"
    )

    print("\n--- Strava OAuth Setup ---")
    print("Opening your browser to authorize coach_claude...")
    print("If the browser doesn't open, visit this URL manually:\n")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)

    print(
        "After clicking 'Authorize', your browser will redirect to a localhost URL.\n"
        "It will look like: http://localhost/?state=&code=XXXXXXXX&scope=...\n"
        "The page won't load (that's fine). Copy the full URL and paste it below.\n"
    )

    redirect = input("Paste the redirect URL here: ").strip()
    if "code=" not in redirect:
        print("No 'code=' found in that URL. Try again.")
        sys.exit(1)

    code = redirect.split("code=")[1].split("&")[0]

    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    refresh_token = data.get("refresh_token", "")
    athlete = data.get("athlete", {})
    name = f"{athlete.get('firstname','')} {athlete.get('lastname','')}".strip()

    print(f"\nAuthorized as: {name or 'unknown athlete'}")
    print(f"\nAdd this to your .env:\n\n  STRAVA_REFRESH_TOKEN={refresh_token}\n")


if __name__ == "__main__":
    main()

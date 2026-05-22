"""
One-time script to get a Google OAuth refresh token covering all APIs used by the pipeline:
  - Google Sheets API
  - Google Drive API
  - YouTube Data API v3
  - YouTube Analytics API

Run this ONCE on your local machine (not the VPS), then copy the refresh token into your .env.

Usage:
    python scripts/get_google_token.py

Prerequisites:
    pip install google-auth-oauthlib

Steps this script walks you through:
    1. Enter your Google Cloud OAuth client_id and client_secret
    2. Open a URL in your browser and sign in with your YouTube/Google account
    3. Paste the authorisation code back here
    4. The script prints your refresh token — paste it into .env as GOOGLE_REFRESH_TOKEN
"""

import json
import sys
import urllib.parse
import urllib.request
import webbrowser

# All scopes the pipeline needs
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"  # "Copy/paste" flow — no local server needed


def _print_step(n: int, text: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  Step {n}: {text}")
    print(f"{'─'*60}")


def _prompt(label: str, secret: bool = False) -> str:
    while True:
        if secret:
            import getpass
            val = getpass.getpass(f"  {label}: ").strip()
        else:
            val = input(f"  {label}: ").strip()
        if val:
            return val
        print("  (cannot be empty — please try again)")


def _build_auth_url(client_id: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # Force consent screen so we always get a refresh token
    }
    return AUTH_URI + "?" + urllib.parse.urlencode(params)


def _exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(TOKEN_URI, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _update_env_file(refresh_token: str, client_id: str, client_secret: str) -> bool:
    """Try to write values into .env if it exists. Returns True if updated."""
    import os
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(env_path):
        return False

    with open(env_path, "r") as f:
        lines = f.readlines()

    replacements = {
        "GOOGLE_REFRESH_TOKEN": refresh_token,
        "GOOGLE_CLIENT_ID": client_id,
        "GOOGLE_CLIENT_SECRET": client_secret,
    }

    new_lines = []
    updated = set()
    for line in lines:
        key = line.split("=")[0].strip()
        if key in replacements:
            new_lines.append(f"{key}={replacements[key]}\n")
            updated.add(key)
        else:
            new_lines.append(line)

    # Append any keys that weren't already in the file
    for key, val in replacements.items():
        if key not in updated:
            new_lines.append(f"{key}={val}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    return True


def main() -> None:
    print("\n" + "═" * 60)
    print("  Google OAuth Token Setup — YouTube Automation Pipeline")
    print("═" * 60)
    print("""
  This script gets a refresh token that gives the pipeline access
  to your Google Sheets, Drive, and YouTube account.

  You only need to run this ONCE. The refresh token never expires
  unless you revoke it.
""")

    # ── Step 1: Google Cloud project setup instructions ──────────────
    _print_step(1, "Create OAuth credentials in Google Cloud Console")
    print("""
  If you haven't already:

  a) Go to: https://console.cloud.google.com/
  b) Create a new project (or select an existing one)
  c) Enable these 4 APIs (search for each in "APIs & Services > Library"):
       • Google Sheets API
       • Google Drive API
       • YouTube Data API v3
       • YouTube Analytics API

  d) Go to "APIs & Services > Credentials"
  e) Click "Create Credentials" → "OAuth client ID"
  f) Application type: Desktop app
  g) Give it any name (e.g. "YouTube Pipeline")
  h) Download or copy the client_id and client_secret shown

  Press Enter when ready...
""")
    input()

    # ── Step 2: Collect credentials ──────────────────────────────────
    _print_step(2, "Enter your OAuth credentials")
    print()
    client_id = _prompt("Client ID (ends with .apps.googleusercontent.com)")
    client_secret = _prompt("Client Secret", secret=True)

    # ── Step 3: Open browser ──────────────────────────────────────────
    _print_step(3, "Authorise access in your browser")
    auth_url = _build_auth_url(client_id)
    print(f"""
  Opening this URL in your browser:
  {auth_url}

  If the browser doesn't open automatically, copy and paste the URL above.

  Sign in with the Google account that owns your YouTube channel.
  Click "Allow" on the consent screen.
  You'll see a page that says "This app isn't verified" — click "Advanced"
  then "Go to [app name] (unsafe)" — this is safe, it's your own app.

  After clicking Allow, Google will show you an authorisation code.
  Copy that code and paste it below.
""")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # Browser open failed — user will copy/paste manually

    input("  Press Enter when you're on the consent screen...")

    # ── Step 4: Exchange code ─────────────────────────────────────────
    _print_step(4, "Enter the authorisation code")
    print()
    auth_code = _prompt("Authorisation code (from Google's page)")

    print("\n  Exchanging code for tokens...")
    try:
        tokens = _exchange_code(client_id, client_secret, auth_code)
    except Exception as exc:
        print(f"\n  ✗ Token exchange failed: {exc}")
        print("  Check that you copied the code correctly and try again.")
        sys.exit(1)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("\n  ✗ No refresh token in response.")
        print("  This can happen if you've authorised this app before.")
        print("  Go to https://myaccount.google.com/permissions, revoke access")
        print("  for this app, then re-run this script.")
        sys.exit(1)

    # ── Step 5: Show results ──────────────────────────────────────────
    _print_step(5, "Your credentials")
    print(f"""
  ✓ Success! Add these to your .env file:

  GOOGLE_CLIENT_ID={client_id}
  GOOGLE_CLIENT_SECRET={client_secret}
  GOOGLE_REFRESH_TOKEN={refresh_token}
""")

    # Try to auto-update .env
    if _update_env_file(refresh_token, client_id, client_secret):
        print("  ✓ Also automatically written to your .env file.")
    else:
        print("  (No .env file found — copy the values above manually.)")

    print("""
  ── What to do next ────────────────────────────────────────────
  1. Create your Google Sheets spreadsheet and note its ID from the URL
     (the long string between /d/ and /edit in the URL bar)
     Set: GOOGLE_SHEETS_ID=<that ID>

  2. Create a "YouTube Pipeline" folder in Google Drive and note its ID
     (right-click → Get link → copy the ID at the end of the URL)
     Set: GOOGLE_DRIVE_ROOT_FOLDER_ID=<that ID>

  3. Fill in the remaining keys in .env (OpenRouter, Groq, OpenAI, etc.)

  4. Test Stage 1: DRY_RUN=true python stage1_brief/run_stage1.py
""")


if __name__ == "__main__":
    main()

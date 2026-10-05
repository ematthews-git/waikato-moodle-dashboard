"""Get a Moodle mobile-web-service token through the site's own SSO login.

Waikato's Moodle signs people in via Microsoft (SAML), so there is no username/password
endpoint to call, and this tool never sees your password. The official Moodle app gets
its token by opening /admin/tool/mobile/launch.php in a browser; after you sign in,
Moodle redirects to `moodlemobile://token=<base64>`. We open the same URL in a browser
window you sign in to, and read that redirect instead of letting it launch an app.

Only the token is kept (a 32-character key, valid for the mobile service only), in
.state/session.json with owner-only permissions. Revoke it any time from your Moodle
profile: Preferences > Security keys.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import time
import urllib.parse
from pathlib import Path

from .config import SERVICE, STATE_DIR

SESSION_FILE = STATE_DIR / "session.json"
PROFILE_DIR = STATE_DIR / "browser-profile"  # keeps your Microsoft session, so re-login is quick

# The scheme is whatever the site's mobile config says (usually moodlemobile), so don't hardcode it.
TOKEN_URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://token=([^&\s]+)")
RAW_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def launch_url(site: str, passport: str) -> str:
    query = urllib.parse.urlencode({"service": SERVICE, "passport": passport, "urlscheme": "moodlemobile"})
    return f"{site.rstrip('/')}/admin/tool/mobile/launch.php?{query}"


def decode_app_token(blob: str) -> str:
    """`base64(siteid:::token[:::privatetoken])` -> token.

    The private token (only for the app's auto-login) is deliberately dropped. The site id
    is md5(wwwroot + passport); we skip checking it because the first real API call
    verifies the token anyway.
    """
    blob = urllib.parse.unquote(blob)
    try:
        parts = base64.b64decode(blob + "=" * (-len(blob) % 4)).decode().split(":::")
    except (binascii.Error, UnicodeDecodeError):
        parts = []
    if len(parts) < 2 or not RAW_TOKEN.match(parts[1]):
        raise ValueError("That doesn't look like a Moodle app token.")
    return parts[1]


def token_from_text(text: str) -> str:
    """Accept a full moodlemobile://token=... URL, the base64 part, or a bare 32-char token."""
    text = text.strip()
    if RAW_TOKEN.match(text):
        return text
    match = TOKEN_URL.match(text)
    return decode_app_token(match.group(1) if match else text)


def save_session(site: str, token: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"site": site.rstrip("/"), "token": token, "saved_at": int(time.time())}, f)
    os.chmod(SESSION_FILE, 0o600)  # O_CREAT's mode is ignored if the file already existed


def load_session() -> dict | None:
    try:
        return json.loads(SESSION_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _header(headers: dict | None, name: str) -> str | None:
    return next((v for k, v in (headers or {}).items() if k.lower() == name), None)


def _launch_browser(playwright, profile_dir: Path, headless: bool):
    # Prefer a browser you already have installed; avoids a ~150 MB Chromium download.
    last = None
    for channel in ("chrome", "msedge", None):
        try:
            options = {"channel": channel} if channel else {}
            return playwright.chromium.launch_persistent_context(
                str(profile_dir), headless=headless, **options
            )
        except Exception as e:  # noqa: BLE001 - Playwright raises plain Errors for a missing browser
            last = e
    raise SystemExit(
        "Couldn't start Chrome, Edge or Playwright's Chromium.\n"
        "Install one of them (or run `playwright install chromium`), or use `login --paste`.\n"
        f"({last})"
    )


def browser_login(site: str, *, profile_dir: Path = PROFILE_DIR, timeout: int = 300, headless: bool = False,
                  log=print) -> str:
    """Open a browser at the launch URL, wait for the SSO redirect, return the token."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Playwright isn't installed: `pip install playwright`, or use `login --paste`.") from None

    found: list[str] = []

    def scan(value):
        match = TOKEN_URL.match(value or "")
        if match:
            found.append(match.group(1))

    def watch(page):
        # The redirect to moodlemobile:// never loads as a page, so catch it at several levels.
        page.on("request", lambda r: scan(r.url))
        page.on("requestfailed", lambda r: scan(r.url))
        page.on("framenavigated", lambda f: scan(f.url))
        try:  # raw redirect headers, straight from Chromium's network layer
            cdp = page.context.new_cdp_session(page)
            cdp.send("Network.enable")
            cdp.on("Network.responseReceivedExtraInfo", lambda e: scan(_header(e.get("headers"), "location")))
            cdp.on(
                "Network.requestWillBeSent",
                lambda e: scan(_header((e.get("redirectResponse") or {}).get("headers"), "location")),
            )
        except Exception:  # noqa: BLE001 - the plain listeners above still work without CDP
            pass

    profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    with sync_playwright() as p:
        context = _launch_browser(p, profile_dir, headless)
        context.on("page", watch)
        page = context.pages[0] if context.pages else context.new_page()
        watch(page)
        log("A browser window is open. Sign in with your Waikato account there (including MFA).")
        try:
            page.goto(launch_url(site, secrets.token_hex(8)))
        except Exception:  # noqa: BLE001 - goto aborts when the redirect leaves http(s); the token is already captured
            pass
        deadline = time.monotonic() + timeout
        try:
            while not found and time.monotonic() < deadline:
                page.wait_for_timeout(250)  # also pumps Playwright's event callbacks
        except Exception:  # noqa: BLE001 - window was closed
            pass
        try:
            context.close()
        except Exception:  # noqa: BLE001
            pass

    if not found:
        raise SystemExit("No token captured (window closed or timed out). Try again, or use `login --paste`.")
    return decode_app_token(found[0])

"""Command line: login -> sync -> serve."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import webbrowser

from . import auth
from .client import InvalidToken, Moodle, MoodleError
from .collect import collect
from .config import DATA_DIR, DEFAULT_SITE
from .demo import DemoClient
from .server import make_server

DATA_FILE = DATA_DIR / "data.json"


def cmd_login(args):
    site = args.site.rstrip("/")
    if args.paste:
        print(f"Open this address in a browser where you're signed in to Moodle:\n\n  {auth.launch_url(site, 'x')}\n")
        print("It will end on a page that fails to open an app. Copy the full moodlemobile://token=... address")
        print("from your browser's DevTools > Network tab (the last redirect's Location header).")
        try:
            token = auth.token_from_text(getpass.getpass("Paste it here (input hidden): "))
        except ValueError as e:
            sys.exit(str(e))
    else:
        token = auth.browser_login(site, timeout=args.timeout)

    try:
        info = Moodle(site, token).call("core_webservice_get_site_info")  # the real check that the token works
    except MoodleError as e:
        sys.exit(f"Moodle didn't accept that token ({e.code}). Nothing was saved.")
    auth.save_session(site, token)
    print(f"Signed in as {info['fullname']}. Token saved to {auth.SESSION_FILE} (owner-only).")


def load_dataset():
    try:
        return json.loads(DATA_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def cmd_sync(_args):
    session = auth.load_session()
    if not session:
        sys.exit("Not logged in yet: run `python -m moodle_dash login` first.")
    try:
        data = collect(Moodle(session["site"], session["token"]))
    except InvalidToken:
        sys.exit("Moodle rejected the saved token (expired or revoked). Run `python -m moodle_dash login` again.")
    except MoodleError as e:
        sys.exit(f"Sync failed: {e}")

    DATA_DIR.mkdir(exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    tmp = DATA_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    tmp.replace(DATA_FILE)  # atomic: the dashboard never sees a half-written file
    marked = sum(1 for c in data["courses"] for a in c["assessments"] if a["percentage"] is not None)
    print(f"Saved {len(data['courses'])} courses, {marked} marked assessments, {len(data['deadlines'])} deadlines.")
    if data["warnings"]:
        print(f"{len(data['warnings'])} warning(s); see the dashboard footer.")


def cmd_serve(args):
    if args.demo:
        def load():
            return {**collect(DemoClient(), log=lambda *_: None), "demo": True}
    else:
        load = load_dataset
        if load() is None:
            print("No synced data yet. Run `python -m moodle_dash sync` first (or try `serve --demo`).")
    server = make_server(load, args.port)
    url = f"http://localhost:{args.port}/"
    print(f"Dashboard at {url}  (Ctrl+C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="moodle_dash", description=__doc__)
    parser.add_argument("--site", default=os.environ.get("MOODLE_URL", DEFAULT_SITE), help="Moodle base URL")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="sign in through your browser and save a token")
    login.add_argument("--paste", action="store_true", help="paste a token instead of opening a browser")
    login.add_argument("--timeout", type=int, default=300, help="seconds to wait for you to sign in")
    login.set_defaults(run=cmd_login)

    sub.add_parser("sync", help="fetch courses, grades and deadlines").set_defaults(run=cmd_sync)

    serve = sub.add_parser("serve", help="show the dashboard on localhost")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--demo", action="store_true", help="use invented data (no login needed)")
    serve.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    serve.set_defaults(run=cmd_serve)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()

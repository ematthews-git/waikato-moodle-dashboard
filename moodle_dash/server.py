"""Serve the dashboard and its data on localhost only."""
from __future__ import annotations

import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .config import DASHBOARD_DIR

LOCAL_NAMES = {"localhost", "127.0.0.1", "[::1]"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, load_data, **kwargs):
        self.load_data = load_data
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        # Refuse requests that arrive under another hostname: stops DNS-rebinding pages
        # from reading your grades through this local server.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_NAMES:
            return self.send_error(403, "Local access only")
        if self.path.split("?")[0] == "/data.json":
            data = self.load_data()
            if data is None:
                return self.send_error(404, "No data yet: run `python -m moodle_dash sync`")
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):  # keep the terminal quiet
        pass


def make_server(load_data, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, load_data=load_data))

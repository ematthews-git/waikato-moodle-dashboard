"""An HTTP fake of the bits of Moodle this tool talks to (web-service endpoint + SSO launch)."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from moodle_dash.demo import DemoClient

TOKEN = "0123456789abcdef0123456789abcdef"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.path == "/webservice/rest/server.php", self.path
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        form = {k: v[0] for k, v in form.items()}
        self.server.calls.append(form["wsfunction"])
        if form.get("wstoken") != TOKEN:  # Moodle: HTTP 200 with an exception object
            return self._json({"exception": "moodle_exception", "errorcode": "invalidtoken",
                               "message": "Invalid token - token not found"})
        params = {k: v for k, v in form.items() if k not in ("wstoken", "wsfunction", "moodlewsrestformat")}
        if form["wsfunction"] in self.server.denied:
            return self._json({"exception": "required_capability_exception", "errorcode": "nopermissions",
                               "message": "Sorry, but you do not currently have permissions to do that"})
        self._json(self.server.demo.call(form["wsfunction"], **params))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != "/admin/tool/mobile/launch.php":
            return self.send_error(404)
        passport = urllib.parse.parse_qs(url.query)["passport"][0]
        site = f"http://127.0.0.1:{self.server.server_port}"
        siteid = hashlib.md5((site + passport).encode()).hexdigest()
        blob = base64.b64encode(f"{siteid}:::{TOKEN}:::privatetokenprivatetoken".encode()).decode()
        self.send_response(303)  # what Moodle does once you are signed in
        self.send_header("Location", f"moodlemobile://token={blob}")
        self.end_headers()


class FakeMoodle(ThreadingHTTPServer):
    def __init__(self, now=1_790_000_000, denied=()):
        super().__init__(("127.0.0.1", 0), Handler)
        self.demo, self.denied, self.calls = DemoClient(now), set(denied), []
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()

"""Minimal Moodle REST web-service client (standard library only)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "waikato-moodle-dashboard/0.1 (personal grade viewer)"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class MoodleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class InvalidToken(MoodleError):
    """The token is unknown, expired or revoked: log in again."""


def flatten(params: dict, prefix: str = "") -> list[tuple[str, object]]:
    """Moodle's REST format wants arrays as key[0]=a and nesting as key[0][sub]=b."""
    out: list[tuple[str, object]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out += flatten(value, name)
        elif isinstance(value, (list, tuple)):
            out += flatten(dict(enumerate(value)), name)
        elif isinstance(value, bool):
            out.append((name, int(value)))
        elif value is not None:
            out.append((name, value))
    return out


class Moodle:
    def __init__(self, site: str, token: str, *, timeout: float = 30, pause: float = 0.15, retries: int = 2):
        site = site.rstrip("/")
        host = urllib.parse.urlparse(site).hostname or ""
        if not site.startswith("https://") and host not in LOCAL_HOSTS:
            raise ValueError(f"Refusing to send a token over plain HTTP to {site}")
        self.site, self.token = site, token
        self.timeout, self.pause, self.retries = timeout, pause, retries

    def call(self, function: str, **params):
        # POST so the token never ends up in a URL (proxy / server logs).
        body = urllib.parse.urlencode(
            [("wstoken", self.token), ("wsfunction", function), ("moodlewsrestformat", "json"), *flatten(params)]
        ).encode()
        request = urllib.request.Request(
            f"{self.site}/webservice/rest/server.php", data=body, headers={"User-Agent": USER_AGENT}
        )
        payload = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == self.retries:
                    raise MoodleError(f"http{e.code}", e.reason) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise MoodleError("network", str(e)) from e
            time.sleep(2**attempt)
        time.sleep(self.pause)  # be polite: we are one student, not a crawler

        # Moodle reports failures as HTTP 200 with an exception object in the body.
        if isinstance(payload, dict) and ("exception" in payload or "errorcode" in payload):
            code, message = payload.get("errorcode", "error"), payload.get("message", "")
            raise (InvalidToken if code == "invalidtoken" else MoodleError)(code, message)
        return payload

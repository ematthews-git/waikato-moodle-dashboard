import contextlib
import io
import json
import stat
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from moodle_dash import __main__ as cli
from moodle_dash import auth
from moodle_dash.server import make_server

from .fake_moodle import TOKEN, FakeMoodle


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [
            mock.patch.object(auth, "STATE_DIR", self.tmp / "state"),
            mock.patch.object(auth, "SESSION_FILE", self.tmp / "state" / "session.json"),
            mock.patch.object(cli, "DATA_DIR", self.tmp / "data"),
            mock.patch.object(cli, "DATA_FILE", self.tmp / "data" / "data.json"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def sync(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.cmd_sync(None)
        return out.getvalue()

    def test_sync_writes_private_files(self):
        with FakeMoodle() as server:
            auth.save_session(server.url, TOKEN)
            out = self.sync()
        self.assertIn("Saved 5 courses", out)
        data = json.loads((self.tmp / "data" / "data.json").read_text())
        self.assertEqual(len(data["courses"]), 5)
        # grades and the token are personal: owner-only, and the token never lands in the data file
        self.assertEqual(mode(auth.SESSION_FILE), 0o600)
        self.assertEqual(mode(self.tmp / "data" / "data.json"), 0o600)
        self.assertEqual(mode(self.tmp / "data"), 0o700)
        self.assertNotIn(TOKEN, json.dumps(data))
        self.assertFalse(list((self.tmp / "data").glob("*.tmp")))

    def test_session_file_stays_private_when_overwritten(self):
        auth.save_session("https://example.test", TOKEN)
        auth.SESSION_FILE.chmod(0o644)  # e.g. loosened by hand
        auth.save_session("https://example.test", TOKEN)
        self.assertEqual(mode(auth.SESSION_FILE), 0o600)

    def test_login_paste_failures_are_plain_messages_and_save_nothing(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        with quiet, mock.patch("getpass.getpass", return_value="garbage"), self.assertRaises(SystemExit) as ctx:
            cli.cmd_login(mock.Mock(site="https://example.test", paste=True))
        self.assertIn("doesn't look like", str(ctx.exception))
        with FakeMoodle() as server, quiet, mock.patch("getpass.getpass", return_value="f" * 32), \
                self.assertRaises(SystemExit) as ctx:  # well-formed but not a real token
            cli.cmd_login(mock.Mock(site=server.url, paste=True))
        self.assertIn("invalidtoken", str(ctx.exception))
        self.assertFalse(auth.SESSION_FILE.exists())

    def test_login_paste_success_saves_private_session(self):
        with FakeMoodle() as server, mock.patch("getpass.getpass", return_value=TOKEN), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_login(mock.Mock(site=server.url, paste=True))
        self.assertEqual(auth.load_session()["token"], TOKEN)
        self.assertEqual(mode(auth.SESSION_FILE), 0o600)

    def test_sync_without_login_explains_what_to_do(self):
        with self.assertRaises(SystemExit) as ctx:
            self.sync()
        self.assertIn("login", str(ctx.exception))

    def test_sync_with_revoked_token_asks_to_log_in_again(self):
        with FakeMoodle() as server:
            auth.save_session(server.url, "f" * 32)
            with self.assertRaises(SystemExit) as ctx:
                self.sync()
        self.assertIn("login", str(ctx.exception))
        self.assertFalse((self.tmp / "data" / "data.json").exists())  # no half-written output


class ServerTests(unittest.TestCase):
    def fetch(self, port, path, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Host": host} if host else {})
        try:
            with urllib.request.urlopen(request) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, b""

    def test_serves_dashboard_and_data_locally_only(self):
        server = make_server(lambda: {"hello": "world"}, port=0)
        port = server.server_address[1]
        import threading

        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        status, body = self.fetch(port, "/data.json")
        self.assertEqual((status, json.loads(body)), (200, {"hello": "world"}))
        self.assertEqual(self.fetch(port, "/")[0], 200)
        # DNS-rebinding defence: a page on evil.example resolving to 127.0.0.1 must not read grades
        self.assertEqual(self.fetch(port, "/data.json", host="evil.example")[0], 403)

    def test_missing_data_is_a_404_not_a_crash(self):
        server = make_server(lambda: None, port=0)
        import threading

        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertEqual(self.fetch(server.server_address[1], "/data.json")[0], 404)


if __name__ == "__main__":
    unittest.main()

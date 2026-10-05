"""Does the browser login actually capture the moodlemobile:// redirect? Needs Playwright and Chrome/Edge."""
import tempfile
import unittest
from pathlib import Path

from moodle_dash import auth

from .fake_moodle import TOKEN, FakeMoodle

try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    playwright = None


@unittest.skipIf(playwright is None, "playwright not installed")
class BrowserCaptureTests(unittest.TestCase):
    def test_captures_token_from_sso_redirect(self):
        with FakeMoodle() as server, tempfile.TemporaryDirectory() as profile:
            token = auth.browser_login(
                server.url, profile_dir=Path(profile), timeout=30, headless=True, log=lambda *_: None
            )
        self.assertEqual(token, TOKEN)


if __name__ == "__main__":
    unittest.main()

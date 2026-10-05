import base64
import unittest

from moodle_dash import auth
from moodle_dash.client import InvalidToken, Moodle, MoodleError, flatten
from moodle_dash.collect import collect, projection
from moodle_dash.demo import DemoClient

from .fake_moodle import TOKEN, FakeMoodle

NOW = 1_790_000_000
quiet = lambda *_: None  # noqa: E731


def course(data, code):
    return next(c for c in data["courses"] if c["code"].startswith(code))


class CollectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = collect(DemoClient(NOW), now=NOW, log=quiet)

    def test_course_status_and_order(self):
        self.assertEqual([c["status"] for c in self.data["courses"]], ["current"] * 4 + ["past"])

    def test_projection_matches_hand_calculation(self):
        # Lab 85% x20 + A1 86% x25 = 38.5 points banked from 45% of the course.
        p = course(self.data, "COMPX234")["projection"]
        self.assertEqual((p["graded_weight"], p["banked"], p["standing"]), (45.0, 38.5, 85.6))
        # (50 - 38.5) / 55 remaining weight
        self.assertEqual(p["needed_for_pass"], 20.9)
        self.assertEqual(p["max_possible"], 93.5)

    def test_moodle_total_is_used_for_grade(self):
        g = course(self.data, "COMPX101")["grade"]
        self.assertEqual((g["percentage"], g["display"]), (81.4, "A-"))
        self.assertEqual(course(self.data, "COMPX101")["projection"]["status"], "final")

    def test_hidden_grade_is_not_leaked(self):
        c = course(self.data, "MNGMT")
        essay = c["assessments"][0]
        self.assertTrue(essay["hidden"])
        self.assertIsNone(essay["percentage"])
        self.assertIsNone(essay["grade"])
        self.assertIsNone(c["grade"]["percentage"])

    def test_feedback_is_plain_text(self):
        fb = course(self.data, "COMPX234")["assessments"][0]["feedback"]
        self.assertEqual(fb, "Solid work. The accessibility section was especially thorough.")

    def test_course_total_row_is_not_an_assessment(self):
        for c in self.data["courses"]:
            self.assertNotIn("course", {a["type"] for a in c["assessments"]})

    def test_teachers_title_and_deadlines(self):
        c = course(self.data, "COMPX234")
        self.assertEqual(c["title"], "Mobile Application Development")  # code prefix stripped
        self.assertEqual(c["teachers"], ["Dr Aroha Williams", "Tane Ngata"])
        due = [d["due"] for d in self.data["deadlines"]]
        self.assertEqual(due, sorted(due))
        self.assertEqual(self.data["deadlines"][0]["name"], "Team project: milestone 2")  # " is due" stripped
        self.assertTrue(self.data["deadlines"][0]["overdue"])

    def test_projection_refuses_when_weights_do_not_add_up(self):
        items = [{"weight": 30, "percentage": 60}, {"weight": 20, "percentage": None}]
        self.assertIsNone(projection(items, 50))

    def test_projection_edge_cases(self):
        item = lambda w, p: {"weight": w, "percentage": p}  # noqa: E731
        out = projection([item(80, 10), item(20, None)], 50)  # 8 banked, only 20 left to earn
        self.assertEqual((out["status"], out["needed_for_pass"]), ("out_of_reach", None))
        self.assertEqual(projection([item(80, 100), item(20, None)], 50)["status"], "secured")


class OverHttpTests(unittest.TestCase):
    def test_full_collect_over_http_matches_in_memory(self):
        with FakeMoodle(NOW) as server:
            over_http = collect(Moodle(server.url, TOKEN, pause=0), now=NOW, log=quiet)
        expected = collect(DemoClient(NOW), now=NOW, log=quiet)
        for d in (over_http, expected):  # the site URL legitimately differs
            for c in d["courses"]:
                c.pop("url"), c.pop("gradebook_url")
            for dl in d["deadlines"]:
                dl.pop("url")
            d.pop("site")
        self.assertEqual(over_http, expected)

    def test_invalid_token(self):
        with FakeMoodle(NOW) as server, self.assertRaises(InvalidToken):
            Moodle(server.url, "f" * 32, pause=0).call("core_webservice_get_site_info")

    def test_one_denied_function_becomes_a_warning_not_a_crash(self):
        with FakeMoodle(NOW, denied={"core_calendar_get_action_events_by_timesort"}) as server:
            data = collect(Moodle(server.url, TOKEN, pause=0), now=NOW, log=quiet)
        self.assertEqual(data["deadlines"], [])
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("deadlines", data["warnings"][0])
        self.assertEqual(len(data["courses"]), 5)

    def test_invalid_token_aborts_the_sync(self):
        with FakeMoodle(NOW) as server, self.assertRaises(InvalidToken):
            collect(Moodle(server.url, "f" * 32, pause=0), now=NOW, log=quiet)

    def test_refuses_plain_http_to_remote_hosts(self):
        with self.assertRaises(ValueError):
            Moodle("http://elearn.waikato.ac.nz", TOKEN)
        Moodle("http://localhost:1234", TOKEN)  # local development is fine

    def test_unreachable_host_is_a_moodle_error(self):
        with self.assertRaises(MoodleError) as ctx:
            Moodle("http://127.0.0.1:1", TOKEN, pause=0, retries=0, timeout=2).call("x")
        self.assertEqual(ctx.exception.code, "network")


class TokenTests(unittest.TestCase):
    def blob(self, *parts):
        return base64.b64encode(":::".join(parts).encode()).decode()

    def test_decodes_app_token_and_drops_private_token(self):
        self.assertEqual(auth.decode_app_token(self.blob("siteid", TOKEN, "private")), TOKEN)

    def test_token_from_text_variants(self):
        blob = self.blob("siteid", TOKEN)
        for text in (TOKEN, f"moodlemobile://token={blob}", blob, f" {blob}\n", f"edu.example://token={blob}"):
            self.assertEqual(auth.token_from_text(text), TOKEN, text)

    def test_rejects_garbage(self):
        for text in ("hello", self.blob("siteid", "not-a-token"), "moodlemobile://token=%%%"):
            with self.assertRaises(ValueError):
                auth.token_from_text(text)

    def test_flatten_follows_moodle_array_syntax(self):
        self.assertEqual(
            flatten({"a": 1, "ids": [5, 6], "n": {"x": True}}),
            [("a", 1), ("ids[0]", 5), ("ids[1]", 6), ("n[x]", 1)],
        )


if __name__ == "__main__":
    unittest.main()

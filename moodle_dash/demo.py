"""A fake Moodle that answers with real web-service response shapes.

It backs `serve --demo` and the tests, so both exercise the same collector code a real
sync does. All names, courses and marks are invented.
"""
from __future__ import annotations

import time

DAY = 86400

# (code, title, started N days ago, ends in N days, teachers, assessments)
# Assessment: (name, module, weight %, mark or None, out of, marked N days ago, feedback, hidden)
COURSES = [
    (101, "COMPX234-26B (HAM)", "Mobile Application Development", 62, 75, ["Dr Aroha Williams", "Tane Ngata"], [
        ("Lab portfolio", "assign", 20, 17, 20, 30, "Solid work. The accessibility section was especially thorough.", False),
        ("Assignment 1: Prototype", "assign", 25, 21.5, 25, 12, "Good navigation design; the data layer needs tests.", False),
        ("Assignment 2: Release build", "assign", 25, None, 25, None, None, False),
        ("Final exam", "quiz", 30, None, 100, None, None, False),
    ]),
    (102, "MATHS165-26B (HAM)", "Discrete Mathematics", 62, 75, ["Prof Mei Zhang"], [
        ("Quiz 1", "quiz", 10, 8, 10, 40, None, False),
        ("Quiz 2", "quiz", 10, 6, 10, 26, None, False),
        ("Quiz 3", "quiz", 10, 5.5, 10, 9, None, False),
        ("Mid-semester test", "quiz", 30, 52, 100, 15, "Induction proofs cost you most of the lost marks.", False),
        ("Final exam", "quiz", 40, None, 100, None, None, False),
    ]),
    (103, "ENGEN101-26B (HAM)", "Engineering Practice", 62, 75, ["Dr Sam Hughes", "Priya Patel"], [
        ("Technical report", "assign", 30, 12, 30, 20, "Structure is unclear; see the marking rubric for the missing sections.", False),
        ("Design presentation", "assign", 20, 9, 20, 5, None, False),
        ("Team project", "assign", 50, None, 100, None, None, False),
    ]),
    (104, "MNGMT102-26B (HAM)", "Introduction to Management", 62, 75, ["Dr Hemi Walker"], [
        ("Essay", "assign", 30, 20, 30, 3, None, True),
        ("Group presentation", "assign", 30, None, 30, None, None, False),
        ("Final exam", "quiz", 40, None, 100, None, None, False),
    ]),
    (90, "COMPX101-26A (HAM)", "Introduction to Programming", 240, -100, ["Dr Aroha Williams"], [
        ("Programming lab 1", "assign", 15, 14, 15, 190, None, False),
        ("Programming lab 2", "assign", 15, 13, 15, 160, None, False),
        ("Project", "assign", 30, 26, 30, 130, "Clean design. Great use of unit tests.", False),
        ("Final exam", "quiz", 40, 71, 100, 110, None, False),
    ]),
]

# (course id, title, module, due in N days, overdue)
EVENTS = [
    (101, "Assignment 2: Release build", "assign", 4, False),
    (102, "Weekly practice quiz", "quiz", 2, False),
    (103, "Team project: milestone 2", "assign", -1, True),
    (103, "Team project", "assign", 21, False),
    (104, "Group presentation", "assign", 9, False),
    (101, "Final exam", "quiz", 38, False),
]

FUNCTIONS = [
    "core_webservice_get_site_info", "core_enrol_get_users_courses", "core_course_get_courses_by_field",
    "gradereport_user_get_grade_items", "gradereport_overview_get_course_grades",
    "core_calendar_get_action_events_by_timesort",
]


def _letter(pct: float) -> str:
    for low, label in [(90, "A+"), (85, "A"), (80, "A-"), (75, "B+"), (70, "B"), (65, "B-"),
                       (60, "C+"), (55, "C"), (50, "C-"), (40, "D"), (0, "E")]:
        if pct >= low:
            return label
    return "E"


class DemoClient:
    """Quacks like moodle_dash.client.Moodle."""

    site = "https://moodle.example.test"

    def __init__(self, now: int | None = None):
        self.now = int(now or time.time())

    def call(self, function: str, **params):
        return getattr(self, f"_{function}")(**params)

    def _core_webservice_get_site_info(self, **_):
        return {
            "sitename": "Demo Moodle", "fullname": "Demo Student", "userid": 4242, "siteurl": self.site,
            "release": "4.5.2 (Build: 20250101)", "functions": [{"name": f, "version": "1"} for f in FUNCTIONS],
        }

    def _core_enrol_get_users_courses(self, **_):
        return [
            {
                "id": cid, "shortname": code, "fullname": f"{code}: {title}", "visible": 1,
                "startdate": self.now - started * DAY, "enddate": self.now + ends * DAY,
                "progress": None if cid == 104 else min(100.0, (started / (started + max(ends, 0) or 1)) * 100),
                "lastaccess": self.now - DAY, "hidden": False,
            }
            for cid, code, title, started, ends, _teachers, _items in COURSES
        ]

    def _core_course_get_courses_by_field(self, value="", **_):
        wanted = {int(v) for v in str(value).split(",") if v}
        return {
            "courses": [
                {"id": cid, "categoryname": "Faculty of Computing and Mathematical Sciences",
                 "contacts": [{"id": 900 + n, "fullname": name} for n, name in enumerate(teachers)]}
                for cid, _code, _title, _s, _e, teachers, _items in COURSES if cid in wanted
            ],
            "warnings": [],
        }

    def _course(self, courseid):
        return next(c for c in COURSES if c[0] == int(courseid))

    def _gradereport_user_get_grade_items(self, courseid, **_):
        cid, _code, _title, _s, _e, _teachers, items = self._course(courseid)
        out, banked, graded_weight = [], 0.0, 0.0
        for n, (name, module, weight, mark, out_of, days_ago, feedback, hidden) in enumerate(items):
            pct = None if mark is None else mark / out_of * 100
            visible_mark = None if hidden else mark
            if mark is not None:
                banked += pct * weight / 100
                graded_weight += weight
            out.append({
                "id": cid * 100 + n, "itemname": name, "itemtype": "mod", "itemmodule": module,
                "iteminstance": n, "itemnumber": 0, "categoryid": 1, "weightformatted": f"{weight:.2f} %",
                "graderaw": visible_mark, "gradeformatted": "-" if visible_mark is None else f"{visible_mark:.2f}",
                "grademin": 0, "grademax": out_of, "gradeishidden": hidden,
                "percentageformatted": "-" if visible_mark is None else f"{pct:.2f} %",
                "gradedategraded": None if days_ago is None else self.now - days_ago * DAY,
                "feedback": f"<p>{feedback}</p>" if feedback and not hidden else "",
            })
        # Moodle's default "natural"/weighted total ignores items nothing has been marked for.
        total = banked / graded_weight * 100 if graded_weight and not all(i[7] for i in items if i[3] is not None) else None
        out.append({
            "id": cid * 100 + 99, "itemname": None, "itemtype": "course", "itemmodule": None,
            "graderaw": total, "grademin": 0, "grademax": 100, "gradeishidden": False,
            "percentageformatted": "-" if total is None else f"{total:.2f} %",
            "lettergradeformatted": "-" if total is None else _letter(total),
            "weightformatted": "-", "feedback": "",
        })
        return {"usergrades": [{"courseid": cid, "userid": 4242, "gradeitems": out}], "warnings": []}

    def _gradereport_overview_get_course_grades(self, **_):
        return {"grades": [{"courseid": c[0], "grade": "-", "rawgrade": None, "rank": 0} for c in COURSES], "warnings": []}

    def _core_calendar_get_action_events_by_timesort(self, **_):
        events = []
        for n, (cid, title, module, due_in, overdue) in enumerate(EVENTS):
            _cid, code, course_title, *_ = self._course(cid)
            link = f"{self.site}/mod/{module}/view.php?id={cid}{n}"
            events.append({
                "id": 5000 + n, "name": f"{title} is due", "timesort": self.now + due_in * DAY, "modulename": module,
                "overdue": overdue, "eventtype": "due", "url": link,
                "course": {"id": cid, "shortname": code, "fullname": course_title},
                "action": {"name": "Add submission" if module == "assign" else "Attempt quiz", "url": link,
                           "itemcount": 1, "actionable": True},
            })
        return {"events": events, "firstid": 5000, "lastid": 5000 + len(EVENTS)}

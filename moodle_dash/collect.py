"""Turn raw Moodle web-service responses into the dashboard's data model (data.json)."""
from __future__ import annotations

import html
import re
import time

from .client import InvalidToken, MoodleError
from .config import GRADE_SCALE, PASS_MARK

DAY = 86400
TOTAL_ITEM_TYPES = {"course", "category"}  # aggregate rows, not assessments
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
TAGS = re.compile(r"<[^>]+>")
EVENT_SUFFIX = re.compile(r"\s+(is due|closes|opens)$", re.I)


def _num(value):
    """Moodle sends numbers as floats, numeric strings, '-' or null."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(text):
    match = NUMBER.search(text or "")
    return float(match.group()) if match else None


def _clean(text) -> str | None:
    """Strip HTML from names and feedback; the dashboard only ever shows plain text."""
    text = html.unescape(TAGS.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip() or None


def _round(value, places=1):
    return None if value is None else round(value, places)


def _item(raw: dict) -> dict:
    gmin = _num(raw.get("grademin")) or 0.0
    gmax = _num(raw.get("grademax"))
    hidden = bool(raw.get("gradeishidden") or raw.get("gradehiddenbydate"))
    grade = None if hidden else _num(raw.get("graderaw"))

    percentage = None
    if grade is not None and gmax is not None and gmax > gmin:
        percentage = (grade - gmin) / (gmax - gmin) * 100
    elif not hidden:
        percentage = _first_number(raw.get("percentageformatted"))

    # Prefer the formatted weight: it always carries its % unit, whereas weightraw's
    # scale (fraction vs percent) differs between Moodle versions.
    weight = _first_number(raw.get("weightformatted"))
    if weight is None:
        weight = _num(raw.get("weightraw"))

    letter = _clean(raw.get("lettergradeformatted"))
    return {
        "id": raw.get("id"),
        "name": _clean(raw.get("itemname")) or "Course total",
        "type": raw.get("itemtype"),
        "module": raw.get("itemmodule") or None,
        "weight": _round(weight, 2),
        "grade": grade,
        "max": gmax,
        "percentage": _round(percentage, 2),
        "letter": None if letter in (None, "-") else letter,
        "hidden": hidden,
        "graded_at": raw.get("gradedategraded") or None,
        "feedback": _clean(raw.get("feedback")),
    }


def projection(items: list[dict], pass_mark: float) -> dict | None:
    """What the marks so far mean, and what the remaining work has to deliver.

    Only trustworthy when item weights add up to ~100% of the course; nested grade
    categories can make the weights Moodle reports relative to a sub-total, so in that
    case we return None rather than show a confident wrong number.
    """
    total_weight = sum(i["weight"] or 0 for i in items)
    if not 95 <= total_weight <= 105:
        return None
    scale = 100 / total_weight
    graded = [i for i in items if i["percentage"] is not None and i["weight"]]
    graded_weight = sum(i["weight"] for i in graded) * scale
    banked = sum(i["percentage"] * i["weight"] / 100 for i in graded) * scale
    remaining = 100 - graded_weight

    if remaining < 0.5:
        status, needed = "final", None
    else:
        needed = (pass_mark - banked) / remaining * 100
        status = "secured" if needed <= 0 else "out_of_reach" if needed > 100 else "reachable"
        needed = None if status == "out_of_reach" else max(needed, 0)
    return {
        "graded_weight": round(graded_weight, 1),
        "remaining_weight": round(remaining, 1),
        "banked": round(banked, 1),  # points already earned, out of 100
        "standing": _round(banked / graded_weight * 100, 1) if graded_weight else None,
        "max_possible": round(banked + remaining, 1),
        "needed_for_pass": _round(needed, 1),
        "status": status,
    }


def _course_status(start, end, now):
    if start and start > now + 14 * DAY:
        return "upcoming"
    if end and end < now - 7 * DAY:
        return "past"
    return "current"


def _strip_code(fullname: str, shortname: str) -> str:
    if shortname and fullname.startswith(shortname):
        fullname = fullname[len(shortname):].lstrip(" :-–—")
    return fullname or shortname


def _deadline(raw: dict) -> dict:
    action = raw.get("action") or {}
    course = raw.get("course") or {}
    name = _clean(raw.get("name")) or "Untitled"
    return {
        "id": raw.get("id"),
        "name": EVENT_SUFFIX.sub("", name),
        "due": raw.get("timesort"),
        "course_id": course.get("id"),
        "module": raw.get("modulename") or None,
        "overdue": bool(raw.get("overdue")),
        "action": _clean(action.get("name")),
        "url": action.get("url") or raw.get("url"),
    }


def collect(client, *, now: int | None = None, pass_mark: float = PASS_MARK, log=print) -> dict:
    now = int(now or time.time())
    warnings: list[str] = []

    def attempt(label, fn, default):
        """One failed call (permissions, a function the site disabled) shouldn't sink the sync."""
        try:
            return fn()
        except InvalidToken:
            raise
        except MoodleError as e:
            warnings.append(f"{label}: {e}")
            log(f"  ! {label}: {e}")
            return default

    info = client.call("core_webservice_get_site_info")
    user_id = info["userid"]
    available = {f["name"] for f in info.get("functions", [])}
    log(f"Signed in as {info.get('fullname')} on {info.get('sitename')}")

    raw_courses = client.call("core_enrol_get_users_courses", userid=user_id, returnusercount=0)
    log(f"Found {len(raw_courses)} courses")

    details = attempt(
        "course details",
        lambda: client.call(
            "core_course_get_courses_by_field", field="ids", value=",".join(str(c["id"]) for c in raw_courses)
        ).get("courses", []),
        [],
    )
    details = {d["id"]: d for d in details}

    overview = {}
    if "gradereport_overview_get_course_grades" in available or not available:
        rows = attempt(
            "course totals",
            lambda: client.call("gradereport_overview_get_course_grades", userid=user_id).get("grades", []),
            [],
        )
        overview = {r["courseid"]: r for r in rows}

    courses = []
    for raw in raw_courses:
        cid = raw["id"]
        log(f"  {raw.get('shortname') or cid}")
        grade_items = attempt(
            f"grades for {raw.get('shortname') or cid}",
            lambda: client.call("gradereport_user_get_grade_items", courseid=cid, userid=user_id)["usergrades"][0][
                "gradeitems"
            ],
            [],
        )
        items = [_item(i) for i in grade_items]
        total = next((i for i in items if i["type"] == "course"), None)
        assessments = [i for i in items if i["type"] not in TOTAL_ITEM_TYPES]
        proj = projection(assessments, pass_mark)

        # Moodle's own course total is authoritative; our standing is only a fallback.
        percentage = total["percentage"] if total else None
        if percentage is None and proj:
            percentage = proj["standing"]
        ov = overview.get(cid, {})
        display = (total or {}).get("letter") or (ov.get("grade") if ov.get("grade") not in (None, "-") else None)
        if percentage is None and display and "%" in str(display):
            percentage = _first_number(display)

        detail = details.get(cid, {})
        courses.append(
            {
                "id": cid,
                "code": raw.get("shortname"),
                "title": _strip_code(raw.get("fullname") or "", raw.get("shortname") or ""),
                "category": detail.get("categoryname") or None,
                "teachers": [_clean(c.get("fullname")) for c in detail.get("contacts", []) if _clean(c.get("fullname"))],
                "start": raw.get("startdate") or None,
                "end": raw.get("enddate") or None,
                "status": _course_status(raw.get("startdate"), raw.get("enddate"), now),
                "hidden": bool(raw.get("hidden")),
                "progress": _round(_num(raw.get("progress")), 1),
                "last_access": raw.get("lastaccess") or None,
                "url": f"{client.site}/course/view.php?id={cid}",
                "gradebook_url": f"{client.site}/grade/report/user/index.php?id={cid}",
                "grade": {
                    "percentage": _round(percentage, 1),
                    "display": display,
                    "rank": ov.get("rank") or None,
                },
                "projection": proj,
                "assessments": assessments,
            }
        )

    order = {"current": 0, "upcoming": 1, "past": 2}
    courses.sort(key=lambda c: (order[c["status"]], -(c["start"] or 0)))

    events = attempt(
        "deadlines",
        lambda: client.call(
            "core_calendar_get_action_events_by_timesort", timesortfrom=now - 14 * DAY, limitnum=50
        ).get("events", []),
        [],
    )
    deadlines = sorted((_deadline(e) for e in events), key=lambda d: d["due"] or 0)

    return {
        "generated_at": now,
        "site": {"name": info.get("sitename"), "url": client.site, "release": info.get("release")},
        "user": {"id": user_id, "name": info.get("fullname")},
        "pass_mark": pass_mark,
        "grade_scale": [{"min": lo, "label": label} for lo, label in GRADE_SCALE],
        "courses": courses,
        "deadlines": deadlines,
        "warnings": warnings,
    }

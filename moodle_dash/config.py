"""Paths and defaults shared across the tool."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".state"  # token + browser profile: secrets, gitignored
DATA_DIR = ROOT / "data"  # synced grades: personal, gitignored
DASHBOARD_DIR = ROOT / "dashboard"

# Waikato's Moodle lives on "elearn", not "moodle". Override with --site or MOODLE_URL.
DEFAULT_SITE = "https://elearn.waikato.ac.nz"

# The service the official Moodle mobile app uses; it is what student tokens can reach.
SERVICE = "moodle_mobile_app"

PASS_MARK = 50.0

# Assumed Waikato letter scale (lower bound, label). Check your own paper outline;
# the dashboard reads this from data.json, so this is the only place to change it.
GRADE_SCALE = [
    (90, "A+"), (85, "A"), (80, "A-"),
    (75, "B+"), (70, "B"), (65, "B-"),
    (60, "C+"), (55, "C"), (50, "C-"),
    (40, "D"), (0, "E"),
]

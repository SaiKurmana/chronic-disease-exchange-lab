"""Project-wide configuration: paths, seeds, dates, labels.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"  # regenerated, git-ignored
RAW_DIR = DATA_DIR / "raw"  # per-organization source FHIR (NDJSON)
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
NETWORK_DIR = DATA_DIR / "network"
EXCHANGE_DIR = DATA_DIR / "exchange"
OUTPUTS_DIR = ROOT / "outputs"  # small, committed, deterministic
EXAMPLES_DIR = ROOT / "examples"
DOCS_DIR = ROOT / "docs"
SITE_DIR = ROOT / "_site"

SEED = 20250101
N_PERSONS = 5000

# Measurement period (calendar-year 2025, i.e. the eCQM 2025 performance period).
MP_START = date(2025, 1, 1)
MP_END = date(2025, 12, 31)
# Simulated "data as of" date when the health department pulls data.
DATA_AS_OF = date(2026, 1, 15)
HISTORY_START = date(2024, 1, 1)

SYNTHETIC_LABEL = "Synthetic data — for demonstration only."
DISCLAIMER = (
    "Independent portfolio project. Not affiliated with, endorsed by, or produced for CDC, "
    "ONC/ASTP, The Sequoia Project, or any QHIN. Not a TEFCA implementation. All data are synthetic."
)
NOT_LEGAL_ADVICE = "This material is descriptive and educational; it is not legal advice."

AUTHOR = "Sai Kurmana, MPH, MS, CPHIMS"
REPO_URL = "https://github.com/saikurmana/chronic-disease-exchange-lab"
# Replace with the deployed Streamlit URL once the app is hosted.
APP_URL = "APP_URL"

# Project-local namespace for synthetic identifiers / code systems (not a real registry).
NS = "https://saikurmana.github.io/chronic-disease-exchange-lab"

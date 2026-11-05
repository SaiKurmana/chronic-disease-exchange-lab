"""The hosted app URL is set, and the "APP_URL" placeholder never reappears in the repo or the site.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from labcore.config import APP_URL
from sitegen.build import build

ROOT = Path(__file__).resolve().parent.parent
LIVE_APP = "https://chronic-disease-exchange.streamlit.app/"
PLACEHOLDER = "APP_URL"
TEXT_SUFFIXES = {".md", ".html", ".txt", ".yml", ".yaml", ".json", ".csv", ".css", ".svg", ".http", ".toml"}


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / f for f in out.splitlines()]


def test_app_url_is_the_live_app():
    assert APP_URL == LIVE_APP


def test_placeholder_absent_from_docs_templates_and_data():
    hits = [
        str(p.relative_to(ROOT))
        for p in _tracked_files()
        if p.suffix in TEXT_SUFFIXES and p.exists() and PLACEHOLDER in p.read_text(encoding="utf-8")
    ]
    assert not hits, f"'{PLACEHOLDER}' placeholder found in: {hits}"


def test_placeholder_not_used_as_a_python_string():
    """The constant's *name* is fine; a string literal "APP_URL" (the old placeholder value) is not."""
    hits = []
    for p in _tracked_files():
        if p.suffix == ".py" and p.exists():
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and node.value == PLACEHOLDER:
                    hits.append(f"{p.relative_to(ROOT)}:{node.lineno}")
    assert not hits, f"string literal '{PLACEHOLDER}' found at: {hits}"


def test_built_site_links_the_live_app(tmp_path):
    out = build(tmp_path / "site")
    for page in out.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert PLACEHOLDER not in text, page
        assert f'href="{LIVE_APP}"' in text, f"nav/footer app link missing in {page}"

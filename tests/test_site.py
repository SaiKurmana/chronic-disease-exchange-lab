"""Static site: builds from committed outputs; every page carries the disclaimer and synthetic label.

Synthetic data — for demonstration only.
"""

import re

from labcore.config import DISCLAIMER, SYNTHETIC_LABEL
from sitegen.build import build


def test_site_builds_with_labels_and_valid_links(tmp_path):
    out = build(tmp_path / "site")
    pages = list(out.rglob("*.html"))
    assert (out / "index.html").exists() and len(pages) >= 10
    for p in pages:
        text = p.read_text(encoding="utf-8")
        assert DISCLAIMER in text, p
        assert SYNTHETIC_LABEL in text, p
        for href in re.findall(r'href="([^"#:]+?)(?:#[^"]*)?"', text):
            if href.startswith(("http", "mailto")):
                continue
            assert (p.parent / href).resolve().exists(), (p.name, href)
    index = (out / "index.html").read_text(encoding="utf-8")
    for chart in ("chart-effects", "chart-svn", "chart-county", "chart-dq"):
        assert f'id="{chart}"' in index

"""Every committed data/document file carries the synthetic-data label; README carries the disclaimer.

Synthetic data — for demonstration only.
"""

from labcore.config import DISCLAIMER, SYNTHETIC_LABEL


def test_committed_files_are_labeled(repo_root):
    missing = []
    for folder in ("outputs", "examples", "docs"):
        for p in (repo_root / folder).rglob("*"):
            if p.is_file() and p.suffix in {".csv", ".json", ".md", ".http", ".ndjson", ".svg", ".html"}:
                text = p.read_text(encoding="utf-8")
                if p.suffix == ".ndjson":
                    ok = all(SYNTHETIC_LABEL in line for line in text.splitlines() if line.strip())
                else:
                    ok = SYNTHETIC_LABEL in text
                if not ok:
                    missing.append(str(p.relative_to(repo_root)))
    assert not missing, missing


def test_readme_disclaimer(repo_root):
    text = (repo_root / "README.md").read_text(encoding="utf-8")
    assert DISCLAIMER in text
    assert "not legal advice" in text.lower()
    assert "Sai Kurmana, MPH, MS, CPHIMS" in text

"""Deterministic file I/O helpers that stamp the synthetic-data label on every file.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from .config import SYNTHETIC_LABEL


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def write_ndjson(path: Path, resources: Iterable[dict]) -> int:
    """Write FHIR resources as NDJSON, sorted by id for deterministic output.

    NDJSON cannot carry comments, so the synthetic label travels inside each resource
    (meta.tag + meta.security HTEST), applied by the generator.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(resources, key=lambda r: (r["resourceType"], r["id"]))
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(dumps(r) + "\n")
    return len(rows)


def read_ndjson(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def parse_ndjson(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def to_ndjson(resources: Iterable[dict]) -> str:
    return "".join(dumps(r) + "\n" for r in resources)


def write_json(path: Path, obj: dict | list, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, dict):
        obj = {"_label": SYNTHETIC_LABEL, **obj}
    path.write_text(
        json.dumps(obj, indent=indent, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> dict | list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_csv(path: Path, df: pd.DataFrame) -> None:
    """CSV with a leading '# Synthetic data' comment line. Read back with read_csv()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n", quoting=csv.QUOTE_MINIMAL, float_format="%.4f")
    path.write_text(f"# {SYNTHETIC_LABEL}\n" + buf.getvalue(), encoding="utf-8")


def read_csv(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, comment="#", **kw)

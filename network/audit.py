"""Append-only, hash-chained audit log stored in DuckDB.

Every broker decision and every node interaction is recorded: who (requester), why (exchange
purpose), what (operation, resource types, counts returned/withheld), when (logical clock), and
outcome. Each row stores the SHA-256 of the previous row, so any edit or deletion breaks the
chain and `verify()` fails.

The API exposes only `append` and read methods (no update/delete). DuckDB has no triggers, so
append-only is enforced by the interface plus the hash chain -- see docs/limitations.md.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

COLUMNS = [
    "seq",
    "event_time",
    "request_id",
    "event_type",
    "requester_id",
    "requester_role",
    "purpose_code",
    "operation",
    "target_node",
    "resource_types",
    "date_range",
    "jurisdiction",
    "outcome",
    "http_status",
    "records_returned",
    "records_withheld",
    "detail",
    "prev_hash",
    "entry_hash",
]
GENESIS = "0" * 64


class LogicalClock:
    """Deterministic clock: each tick advances one second from a fixed start."""

    def __init__(self, start: datetime | None = None):
        self.t = start or datetime(2026, 1, 16, 9, 0, 0, tzinfo=UTC)

    def tick(self) -> str:
        self.t += timedelta(seconds=1)
        return self.t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _canon(v) -> str:
    """Canonical string form so the chain verifies after CSV / DataFrame round-trips."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _hash(row: dict) -> str:
    payload = json.dumps({k: _canon(row[k]) for k in COLUMNS if k != "entry_hash"}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path | str = ":memory:", clock: LogicalClock | None = None):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            if Path(self.path).exists():
                Path(self.path).unlink()  # each pipeline run starts a fresh, reproducible log
        self.con = duckdb.connect(self.path)
        self.con.execute(
            "CREATE TABLE audit_log (seq INTEGER PRIMARY KEY, event_time VARCHAR, request_id VARCHAR, "
            "event_type VARCHAR, requester_id VARCHAR, requester_role VARCHAR, purpose_code VARCHAR, "
            "operation VARCHAR, target_node VARCHAR, resource_types VARCHAR, date_range VARCHAR, "
            "jurisdiction VARCHAR, outcome VARCHAR, http_status INTEGER, records_returned INTEGER, "
            "records_withheld INTEGER, detail VARCHAR, prev_hash VARCHAR, entry_hash VARCHAR)"
        )
        self.clock = clock or LogicalClock()
        self._seq = 0
        self._last = GENESIS

    def append(self, **fields) -> dict:
        self._seq += 1
        row = {c: None for c in COLUMNS}
        row.update({k: v for k, v in fields.items() if k in COLUMNS})
        row.update(seq=self._seq, event_time=self.clock.tick(), prev_hash=self._last)
        for k in ("records_returned", "records_withheld"):
            row[k] = int(row[k] or 0)
        row["entry_hash"] = _hash(row)
        self.con.execute(
            f"INSERT INTO audit_log VALUES ({', '.join('?' * len(COLUMNS))})", [row[c] for c in COLUMNS]
        )
        self._last = row["entry_hash"]
        return row

    def df(self) -> pd.DataFrame:
        return self.con.execute("SELECT * FROM audit_log ORDER BY seq").df()

    def verify(self, df: pd.DataFrame | None = None) -> tuple[bool, str]:
        df = self.df() if df is None else df
        return verify_frame(df)

    def close(self) -> None:
        self.con.close()


def verify_frame(df: pd.DataFrame) -> tuple[bool, str]:
    prev = GENESIS
    for i, rec in enumerate(df.to_dict("records")):
        row = {c: rec.get(c) for c in COLUMNS}
        if _canon(row["seq"]) != str(i + 1):
            return False, f"sequence gap at row {i + 1}"
        if _canon(row["prev_hash"]) != prev:
            return False, f"broken chain at seq {row['seq']}"
        if _hash(row) != _canon(row["entry_hash"]):
            return False, f"entry hash mismatch at seq {row['seq']} (row altered)"
        prev = _canon(row["entry_hash"])
    return True, f"{len(df)} entries verified"

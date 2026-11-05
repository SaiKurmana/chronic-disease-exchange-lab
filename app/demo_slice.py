"""Write a small, committed slice of the simulated source data (outputs/demo_network/) so the
Streamlit "send a request" simulator runs offline without regenerating 5,000 patients.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from labcore.config import OUTPUTS_DIR, RAW_DIR
from labcore.io import read_csv, read_ndjson, write_ndjson
from synth.orgs import ORGS

DEMO_DIR = OUTPUTS_DIR / "demo_network"
TYPES = ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest", "Organization"]


def build(raw_dir: Path = RAW_DIR, out: Path = DEMO_DIR, per_node: int = 10) -> int:
    links = read_csv(raw_dir.parent / "ground_truth" / "links.csv", dtype=str).fillna("")
    # Prefer people seen at 2+ organizations (shows duplicates and cross-org data), then fill up.
    multi = sorted(links.groupby("person_id").filter(lambda g: len(g) > 1)["person_id"].unique())[:12]
    keep: dict[str, set[str]] = {o.id: set() for o in ORGS}
    for r in links[links.person_id.isin(multi)].itertuples():
        keep[r.org_id].add(r.patient_id)
    for o in ORGS:
        extra = sorted(links[links.org_id == o.id].patient_id)[: max(0, per_node - len(keep[o.id]))]
        keep[o.id].update(extra)
    if out.exists():
        shutil.rmtree(out)
    n = 0
    for o in ORGS:
        for t in TYPES:
            rows = read_ndjson(raw_dir / o.id / f"{t}.ndjson")
            if t == "Patient":
                rows = [r for r in rows if r["id"] in keep[o.id]]
            elif t != "Organization":
                rows = [
                    r for r in rows if r.get("subject", {}).get("reference", "").split("/")[-1] in keep[o.id]
                ]
            n += write_ndjson(out / o.id / f"{t}.ndjson", rows)
    return n


if __name__ == "__main__":
    print(f"Demo slice: {build()} resources written to {DEMO_DIR}")

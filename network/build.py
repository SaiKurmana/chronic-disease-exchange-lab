"""`make network`: stand up the simulated nodes in-process, health-check them, and publish the
network directory (outputs/network_directory.json).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from labcore.config import DATA_AS_OF, OUTPUTS_DIR, RAW_DIR
from labcore.io import write_json

from .broker import Broker


def build(raw_dir=RAW_DIR, outputs_dir=OUTPUTS_DIR) -> dict:
    if not (raw_dir / "amc" / "Patient.ndjson").exists():
        raise SystemExit("No source data found. Run `make data` first.")
    broker = Broker(raw_dir)
    directory = broker.directory()
    for n in directory["nodes"]:
        cli = broker.nodes[n["id"]]
        cap = cli.get("/metadata").json()
        store = cli.app.state.store
        n["health"] = "ok" if cap.get("fhirVersion") == "4.0.1" else "error"
        n["resources_visible"] = {t: len(v) for t, v in sorted(store.by_type.items())}
        n["resources_pending_as_of"] = dict(sorted(store.pending.items()))
    directory["as_of"] = DATA_AS_OF.isoformat()
    write_json(outputs_dir / "network_directory.json", directory)
    return directory


def main() -> None:
    d = build()
    for n in d["nodes"]:
        vis = sum(n["resources_visible"].values())
        pend = sum(n["resources_pending_as_of"].values())
        print(
            f"  node {n['id']:<5} {n['health']:<3} {vis:>6} resources visible, {pend:>5} not yet loaded "
            f"as of {d['as_of']}  ({n['name']})"
        )
    print("Network directory written to outputs/network_directory.json")


if __name__ == "__main__":
    main()

"""Small end-to-end simulation used by CI and the test suite (fast, deterministic).

    python -m tests.simulate_small                 # run and print summary
    python -m tests.simulate_small --write-golden  # refresh tests/golden/small_sim.json

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from exchange.run import run as run_exchange
from measures.run import run as run_measures
from network.build import build as build_network
from synth.generate import generate

SMALL_N = 800
SMALL_SEED = 7
GOLDEN = Path(__file__).parent / "golden" / "small_sim.json"


def simulate(root: Path, n: int = SMALL_N, seed: int = SMALL_SEED, validate: bool = True) -> dict:
    data = root / "data"
    outputs = root / "outputs"
    generate(n, seed, data)
    build_network(data / "raw", outputs)
    ex = run_exchange(data / "raw", data / "ground_truth", data / "exchange", outputs, root / "examples")
    ms = run_measures(data / "exchange", data / "ground_truth", outputs, validate=validate)
    return {"root": str(root), "exchange": ex, "measures": ms}


def golden_view(result: dict) -> dict:
    ms, ex = result["measures"], result["exchange"]
    return {
        "headline": ms["headline"],
        "effects": ms["effects"],
        "population": ms["population"],
        "dedup": {
            k: ex["dedup"][k] for k in ("records", "true_persons", "predicted_persons", "precision", "recall")
        },
        "audit_entries": ex["audit"]["entries"],
        "denials": [[d["slug"], d["status"]] for d in ex["denials"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-golden", action="store_true")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        g = golden_view(simulate(Path(tmp)))
    print(json.dumps(g, indent=2))
    if a.write_golden:
        GOLDEN.write_text(json.dumps(g, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {GOLDEN}")


if __name__ == "__main__":
    main()

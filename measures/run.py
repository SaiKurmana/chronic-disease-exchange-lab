"""`make measures`: compute surveillance measures, pipeline-effect comparisons, single-organization
vs network views, and per-node data quality. Writes small CSV/JSON files to outputs/.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from labcore.config import DATA_DIR, MP_END, MP_START, OUTPUTS_DIR
from labcore.io import read_csv, read_json, write_csv, write_json
from synth.orgs import ORGS

from .compute import MEASURES, NETWORK_VIEWS, View, person_level, rates, stratified
from .data_quality import METRIC_LABELS, quality_report


def _flat(view: View, df: pd.DataFrame) -> dict:
    row = {"view": view.key, "label": view.label, "persons": int(len(df))}
    for k, r in rates(df).items():
        row.update({f"{k}_num": r["numerator"], f"{k}_den": r["denominator"], f"{k}_rate": r["rate"]})
    return row


def ground_truth_row(oracle: pd.DataFrame, gt_dir: Path) -> dict:
    """Latent ('true') disease status for the same qualifying population (includes undiagnosed)."""
    persons = read_csv(gt_dir / "persons.csv", dtype={"person_id": str})
    m = oracle[["person_key", "adult"]].merge(persons, left_on="person_key", right_on="person_id")
    ad = m[m["adult"]]
    as_bool = {"True": True, "False": False, True: True, False: False}
    t_htn = ad["true_htn"].map(as_bool)
    t_dm = ad["true_dm"].map(as_bool)
    d_htn = ad["htn_diagnosed"].map(as_bool)
    return {
        "view": "ground_truth",
        "label": "Ground truth: latent disease incl. undiagnosed (same population)",
        "persons": int(len(m)),
        "htn_prevalence_num": int(t_htn.sum()),
        "htn_prevalence_den": int(len(ad)),
        "htn_prevalence_rate": round(float(t_htn.mean()), 4),
        "dm_prevalence_num": int(t_dm.sum()),
        "dm_prevalence_den": int(len(ad)),
        "dm_prevalence_rate": round(float(t_dm.mean()), 4),
        "htn_diagnosed_rate": round(float(d_htn.mean()), 4),
    }


def single_vs_network(con, linked: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    xw = con.execute("SELECT node || ':' || patient_key AS rec, person_key FROM xw_linked").df()
    rows, singles = [], []
    for o in ORGS:
        v = View(f"single_org:{o.id}", f"{o.name} only", "mapped", "none", node=o.id)
        s = person_level(con, v)
        singles.append(_flat(v, s))
        cohort = s.merge(xw, left_on="person_key", right_on="rec", suffixes=("_org", ""))
        net = linked[linked["person_key"].isin(cohort["person_key"])]
        so, nw = rates(s[s["adult"]]), rates(net[net["adult"]])
        cden = net[net["cbp_den"]]
        rows.append(
            {
                "org": o.id,
                "org_name": o.name,
                "adult_patients_with_visit": int(s["adult"].sum()),
                "pct_with_records_at_other_orgs": round(100 * float((net["n_nodes"] > 1).mean()), 1),
                **{f"{k}_org_only": so[k]["rate"] for k in MEASURES},
                **{f"{k}_network": nw[k]["rate"] for k in MEASURES},
                **{f"{k}_den_org_only": so[k]["denominator"] for k in ("cbp", "gsd_gt9")},
                **{f"{k}_den_network": nw[k]["denominator"] for k in ("cbp", "gsd_gt9")},
                "pct_latest_bp_from_other_org": round(
                    100 * float((cden["bp_node"].notna() & (cden["bp_node"] != o.id)).mean()), 1
                )
                if len(cden)
                else None,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(singles)


def run(exchange_dir: Path, gt_dir: Path, outputs_dir: Path, validate: bool = True) -> dict:
    con = duckdb.connect(str(exchange_dir / "analytic.duckdb"), read_only=True)
    frames = {v.key: person_level(con, v) for v in NETWORK_VIEWS}
    linked = frames["network_linked"]
    effects = pd.DataFrame(
        [_flat(v, frames[v.key]) for v in NETWORK_VIEWS]
        + [ground_truth_row(frames["network_oracle"], gt_dir)]
    )
    svn, singles = single_vs_network(con, linked)
    strat = stratified(linked, "network_linked")
    con.close()

    directory_path = outputs_dir / "network_directory.json"
    pending = {}
    if directory_path.exists():
        pending = {
            n["id"]: sum(n.get("resources_pending_as_of", {}).values())
            for n in read_json(directory_path)["nodes"]
        }
    dq = quality_report(exchange_dir / "received", pending, validate=validate)

    write_csv(outputs_dir / "pipeline_effects.csv", effects)
    write_csv(outputs_dir / "single_vs_network.csv", svn)
    write_csv(outputs_dir / "single_org_measures.csv", singles)
    write_csv(outputs_dir / "measures_by_stratum.csv", strat)
    write_csv(outputs_dir / "data_quality_by_node.csv", dq)

    ex = (
        read_json(outputs_dir / "exchange_summary.json")
        if (outputs_dir / "exchange_summary.json").exists()
        else {}
    )
    e = effects.set_index("view")
    head = rates(linked)
    summary = {
        "measurement_period": {"start": MP_START.isoformat(), "end": MP_END.isoformat()},
        "population": {
            "persons_with_qualifying_visit": int(len(linked)),
            "adults": int(linked["adult"].sum()),
        },
        "headline": head,
        "measure_labels": {k: v[0] for k, v in MEASURES.items()},
        "effects": {
            "persons_naive_vs_linked": [
                int(e.loc["network_mapped", "persons"]),
                int(e.loc["network_linked", "persons"]),
            ],
            "htn_prevalence_as_received": e.loc["network_as_received", "htn_prevalence_rate"],
            "htn_prevalence_full_pipeline": e.loc["network_linked", "htn_prevalence_rate"],
            "htn_prevalence_ground_truth_latent": e.loc["ground_truth", "htn_prevalence_rate"],
            "cbp_as_received": e.loc["network_as_received", "cbp_rate"],
            "cbp_full_pipeline": e.loc["network_linked", "cbp_rate"],
            "gsd_as_received": e.loc["network_as_received", "gsd_gt9_rate"],
            "gsd_full_pipeline": e.loc["network_linked", "gsd_gt9_rate"],
        },
        "dedup": {
            k: ex.get("dedup", {}).get(k)
            for k in ("precision", "recall", "f1", "records", "predicted_persons", "true_persons")
        },
        "dq_metric_labels": METRIC_LABELS,
    }
    write_json(outputs_dir / "measures_summary.json", json.loads(json.dumps(summary, default=float)))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute measures")
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--outputs", type=Path, default=OUTPUTS_DIR)
    a = ap.parse_args()
    s = run(a.data / "exchange", a.data / "ground_truth", a.outputs)
    h = s["headline"]
    print(
        f"Network (full pipeline), MP {s['measurement_period']['start']}..{s['measurement_period']['end']}: "
        f"{s['population']['adults']} adults with a qualifying visit"
    )
    for k, r in h.items():
        print(
            f"  {s['measure_labels'][k]:<55} {r['numerator']:>5}/{r['denominator']:<5} = {100 * r['rate']:.1f}%"
        )
    print(f"Effects: {json.dumps(s['effects'])}")


if __name__ == "__main__":
    main()

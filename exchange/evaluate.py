"""Evaluate deduplication against retained ground truth (never visible to the simulated PHA).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pandas as pd

from labcore.io import read_csv
from network.broker import ph_pseudonym


def truth_crosswalk(gt_dir: Path, requester_id: str = "lkdph") -> pd.DataFrame:
    """Ground-truth (node, patient_key -> person_id) using the broker's pseudonym function."""
    links = read_csv(gt_dir / "links.csv", dtype=str)
    rows = []
    for node, grp in links.groupby("org_id"):
        for r in grp.itertuples():
            rows.append(
                {
                    "node": node,
                    "patient_key": ph_pseudonym(requester_id, node, r.patient_id),
                    "person_id": r.person_id,
                    "patient_id": r.patient_id,
                    "variations": r.variations if isinstance(r.variations, str) else "",
                }
            )
    return pd.DataFrame(rows)


def _pairs(xw: pd.DataFrame, key: str) -> set[tuple]:
    out = set()
    for _, g in xw.groupby(key):
        recs = sorted(zip(g["node"], g["patient_key"], strict=True))
        for a, b in combinations(recs, 2):
            if a[0] != b[0]:
                out.add((a, b))
    return out


def evaluate_linkage(pred: pd.DataFrame, truth: pd.DataFrame) -> dict:
    m = pred.merge(truth, on=["node", "patient_key"], how="inner")
    tp_set = _pairs(m, "person_id")
    pred_set = _pairs(m, "person_key")
    tp = len(tp_set & pred_set)
    fp = len(pred_set - tp_set)
    fn = len(tp_set - pred_set)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    # Which demographic variations caused misses?
    missed = _missed_by_variation(m, tp_set - pred_set)
    return {
        "records": int(len(m)),
        "true_persons": int(m["person_id"].nunique()),
        "predicted_persons": int(m["person_key"].nunique()),
        "naive_persons_no_dedup": int(len(m)),
        "true_cross_org_pairs": len(tp_set),
        "predicted_pairs": len(pred_set),
        "true_positive_pairs": tp,
        "false_positive_pairs": fp,
        "false_negative_pairs": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "missed_pairs_by_variation": missed,
    }


def _missed_by_variation(m: pd.DataFrame, missed_pairs: set) -> dict:
    var = {(r.node, r.patient_key): r.variations for r in m.itertuples()}
    out: dict[str, int] = {}
    for a, b in missed_pairs:
        v = "|".join(sorted({x for x in (var.get(a, "") + "|" + var.get(b, "")).split("|") if x})) or "none"
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

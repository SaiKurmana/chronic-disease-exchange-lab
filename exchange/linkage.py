"""Cross-organization deduplication using PPRL tokens (no clear-text identifiers).

Records from different nodes are linked when they share a token combination listed in
labcore.pprl.LINK_RULES; links are closed transitively with union-find. Evaluation against
ground truth lives in exchange/evaluate.py (the PHA never sees ground truth).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from labcore.pprl import LINK_RULES


class UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def link(patients: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (crosswalk[node, patient_key, person_key], candidate_pairs[a, b, rule])."""
    recs = patients[["node", "patient_key", "T1", "T2", "T3", "T4", "T5"]].to_dict("records")
    keys = [(r["node"], r["patient_key"]) for r in recs]
    uf = UnionFind(keys)
    pairs = {}
    for rule in LINK_RULES:
        blocks: dict[tuple, list] = defaultdict(list)
        for r, k in zip(recs, keys, strict=True):
            vals = tuple(r[t] for t in rule)
            if all(vals):
                blocks[vals].append(k)
        for members in blocks.values():
            if len(members) < 2:
                continue
            members = sorted(members)
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    if a[0] == b[0]:
                        continue  # same node: different patients at one organization
                    pairs.setdefault((a, b), "+".join(rule))
                    uf.union(a, b)
    roots = sorted({uf.find(k) for k in keys})
    pid = {r: f"L{i + 1:05d}" for i, r in enumerate(roots)}
    xw = pd.DataFrame([{"node": k[0], "patient_key": k[1], "person_key": pid[uf.find(k)]} for k in keys])
    pr = pd.DataFrame(
        [
            {"a_node": a[0], "a_key": a[1], "b_node": b[0], "b_key": b[1], "rule": rule}
            for (a, b), rule in sorted(pairs.items())
        ],
        columns=["a_node", "a_key", "b_node", "b_key", "rule"],
    )
    return xw.sort_values(["node", "patient_key"]).reset_index(drop=True), pr


def no_link(patients: pd.DataFrame) -> pd.DataFrame:
    """Naive view: every patient record is treated as a distinct person."""
    xw = patients[["node", "patient_key"]].copy()
    xw["person_key"] = xw["node"] + ":" + xw["patient_key"]
    return xw

"""Measure logic on hand-built cases, plus a regression test against the golden small simulation.

Synthetic data — for demonstration only.
"""

import json

import duckdb
import pandas as pd
import pytest

from measures.compute import View, person_level, rates
from tests.simulate_small import GOLDEN, golden_view

P = [  # patient_key, birth_date
    ("A", "1965-03-01"),
    ("B", "1970-01-01"),
    ("C", "1960-01-01"),
    ("D", "1955-01-01"),
    ("E", "1935-01-01"),
    ("F", "2009-06-01"),
    ("G", "1975-01-01"),
    ("H", "1980-01-01"),
    ("I", "1945-01-01"),
    ("J", "1970-01-01"),
    ("K", "1972-02-02"),
]
COND = [  # patient_key, group, onset
    ("A", "htn", "2020-01-01"),
    ("B", "htn", "2025-08-01"),
    ("C", "htn", "2010-01-01"),
    ("C", "esrd", "2019-01-01"),
    ("D", "htn", "2015-01-01"),
    ("E", "htn", "2000-01-01"),
    ("G", "dm", "2018-01-01"),
    ("H", "dm", "2019-01-01"),
    ("I", "dm", "2010-01-01"),
    ("J", "htn", "2010-01-01"),
    ("K", "htn", "2025-06-30"),
]
BP = [  # patient_key, date, sys, dia, enc_class
    ("A", "2025-11-01", 150, 80, "AMB"),
    ("A", "2025-11-01", 135, 95, "AMB"),
    ("A", "2025-12-15", 160, 100, "EMER"),
    ("C", "2025-06-01", 120, 70, "AMB"),
    ("E", "2025-04-01", 120, 70, "AMB"),
    ("K", "2025-09-01", 128, 82, "AMB"),
    ("B", "2025-09-01", 120, 70, "AMB"),
    ("D", "2024-11-01", 120, 70, "AMB"),
]
A1C = [
    ("G", "2025-03-01", 9.5),
    ("G", "2025-10-01", 9.4),
    ("G", "2025-10-01", 8.8),
    ("I", "2025-02-01", 10.2),
]


@pytest.fixture(scope="module")
def frame():
    con = duckdb.connect()
    pats = pd.DataFrame(
        [
            {
                "node": "x",
                "patient_key": k,
                "birth_date": b,
                "gender": "female",
                "county": "Harbor County",
                "rurality": "Urban",
                "race": None,
                "ethnicity": None,
            }
            for k, b in P
        ]
    )
    encs = pd.DataFrame(
        [
            {
                "node": "x",
                "patient_key": k,
                "encounter_id": f"e{k}",
                "date": "2024-05-01" if k == "J" else "2025-05-01",
                "class": "AMB",
            }
            for k, _ in P
        ]
    )
    conds = pd.DataFrame(
        [
            {"node": "x", "patient_key": k, "group": g, "onset": o, "clinical_status": "active"}
            for k, g, o in COND
        ]
    )
    bp = pd.DataFrame(
        [
            {"node": "x", "patient_key": k, "date": d, "sys": s, "dia": di, "enc_class": c}
            for k, d, s, di, c in BP
        ]
    )
    a1c = pd.DataFrame([{"node": "x", "patient_key": k, "date": d, "value_pct": v} for k, d, v in A1C])
    for name, df in {"patients": pats, "encounters": encs, "conditions": conds, "bp": bp, "a1c": a1c}.items():
        con.register(f"mapped_{name}", df)
    df = person_level(con, View("t", "test", "mapped", "none"))
    return df.assign(pk=df["person_key"].str.split(":").str[1]).set_index("pk")


def test_population_requires_qualifying_visit(frame):
    assert "J" not in frame.index and "A" in frame.index


def test_cbp_logic(frame):
    f = frame
    assert bool(f.loc["A", "cbp_num"])  # lowest systolic & lowest diastolic of most recent non-ED day: 135/80
    assert not f.loc["B", "cbp_den"]  # onset after first six months
    assert f.loc["K", "cbp_den"] and f.loc["K", "cbp_num"]  # onset on 2025-06-30 boundary
    assert f.loc["C", "cbp_excl"] and not f.loc["C", "cbp_den"]  # ESRD exclusion
    assert f.loc["D", "cbp_den"] and not f.loc["D", "cbp_num"]  # no BP in MP -> not controlled
    assert not f.loc["E", "cbp_den"]  # age > 85
    r = rates(f)["cbp"]
    assert (r["numerator"], r["denominator"]) == (2, 3)  # A, K controlled; D not


def test_glycemic_logic(frame):
    f = frame
    assert f.loc["G", "gsd_den"] and not f.loc["G", "gsd_num"]  # most recent day, lowest value 8.8
    assert f.loc["H", "gsd_num"] and f.loc["H", "gsd_missing"]  # no test -> counts as poor control
    assert not f.loc["I", "gsd_den"]  # age > 75


def test_prevalence_counts_adults_only(frame):
    r = rates(frame)
    assert r["htn_prevalence"]["denominator"] == 9  # 10 with visits minus F (age 16)
    assert r["htn_prevalence"]["numerator"] == 6  # A B C D E K
    assert r["dm_prevalence"]["numerator"] == 3


def test_regression_against_golden(sim):
    golden = json.loads(GOLDEN.read_text())
    got = json.loads(json.dumps(golden_view(sim), sort_keys=True))
    assert got == golden, (
        "Small-simulation results changed; if intended run `make golden` and review the diff."
    )


def test_exchange_adds_information(sim):
    e = sim["measures"]["effects"]
    assert e["persons_naive_vs_linked"][1] < e["persons_naive_vs_linked"][0]  # dedup reduces person count
    assert e["htn_prevalence_full_pipeline"] > e["htn_prevalence_as_received"]  # mapping recovers local codes
    assert e["htn_prevalence_ground_truth_latent"] > e["htn_prevalence_full_pipeline"]  # undiagnosed remain

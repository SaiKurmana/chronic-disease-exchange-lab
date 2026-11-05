"""Population measures computed with DuckDB over the normalized exchange tables.

Measures (simplified from public eCQM specifications; every simplification is listed in
docs/use_case.md#measure-specifications and docs/limitations.md):

* HTN prevalence  -- adults (18+) with a qualifying ambulatory visit in the measurement period (MP)
                     who have an active hypertension diagnosis with onset on/before MP end.
* DM prevalence   -- same denominator; active diabetes (type 1 or 2) diagnosis.
* CBP             -- adapted from CMS165v13 "Controlling High Blood Pressure" (2025 period):
                     age 18-85 at MP end, qualifying visit in MP, essential hypertension starting
                     before or during the first six months of the MP; exclude ESRD. Numerator: most
                     recent BP date in the MP (excluding ED / inpatient readings), using the lowest
                     systolic and lowest diastolic that day, is <140 and <90. No BP = not controlled.
* GSD>9 (inverse) -- adapted from CMS122v13 "Diabetes: Glycemic Status Assessment Greater Than 9%":
                     age 18-75, diabetes, qualifying visit in MP. Numerator: most recent HbA1c in the
                     MP (lowest value if several that day) is >9.0%, or no HbA1c in the MP. Lower is better.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from labcore.config import MP_END, MP_START

CBP_ONSET_CUTOFF = "2025-06-30"  # end of the first six months of the 2025 measurement period


@dataclass(frozen=True)
class View:
    key: str
    label: str
    mode: str  # "mapped" | "unmapped"
    crosswalk: str  # "none" | "linked" | "oracle"
    node: str | None = None


NETWORK_VIEWS = [
    View(
        "network_as_received", "Network, as received (no code mapping, no deduplication)", "unmapped", "none"
    ),
    View("network_mapped", "+ code & unit mapping (no deduplication)", "mapped", "none"),
    View("network_linked", "+ PPRL deduplication (full pipeline)", "mapped", "linked"),
    View("network_oracle", "Full pipeline with perfect (ground-truth) linkage", "mapped", "oracle"),
]


def _xw_sql(view: View) -> str:
    if view.crosswalk == "none":
        return f"SELECT node, patient_key, node || ':' || patient_key AS person_key FROM {view.mode}_patients"
    return f"SELECT node, patient_key, person_key FROM xw_{view.crosswalk}"


def person_level(con: duckdb.DuckDBPyConnection, view: View) -> pd.DataFrame:
    m = view.mode
    where = f"WHERE t.node = '{view.node}'" if view.node else ""
    mp0, mp1 = MP_START.isoformat(), MP_END.isoformat()
    sql = f"""
    WITH xw AS ({_xw_sql(view)}),
    pat AS (SELECT x.person_key, t.* FROM {m}_patients t JOIN xw x USING (node, patient_key) {where}),
    enc AS (SELECT x.person_key, t.* FROM {m}_encounters t JOIN xw x USING (node, patient_key) {where}),
    cond AS (SELECT x.person_key, t.* FROM {m}_conditions t JOIN xw x USING (node, patient_key) {where}),
    bp AS (SELECT x.person_key, t.* FROM {m}_bp t JOIN xw x USING (node, patient_key) {where}),
    a1c AS (SELECT x.person_key, t.* FROM {m}_a1c t JOIN xw x USING (node, patient_key) {where}),
    lastenc AS (SELECT node, patient_key, max(date) AS d FROM enc GROUP BY 1, 2),
    rk AS (SELECT p.*, coalesce(l.d, '0000') || '|' || p.node || '|' || p.patient_key AS k
           FROM pat p LEFT JOIN lastenc l USING (node, patient_key)),
    person AS (
      SELECT person_key,
        arg_max(birth_date, k) AS birth_date,
        coalesce(arg_max(gender, k) FILTER (WHERE gender <> 'unknown'), 'unknown') AS sex,
        arg_max(county, k) FILTER (WHERE county IS NOT NULL) AS county,
        arg_max(rurality, k) FILTER (WHERE rurality IS NOT NULL) AS rurality,
        arg_max(race, k) FILTER (WHERE race IS NOT NULL) AS race,
        arg_max(ethnicity, k) FILTER (WHERE ethnicity IS NOT NULL) AS ethnicity,
        count(*) AS n_records, count(DISTINCT node) AS n_nodes
      FROM rk GROUP BY 1),
    qual AS (SELECT person_key, node, count(*) AS n, max(date) AS last_visit FROM enc
             WHERE class = 'AMB' AND date BETWEEN '{mp0}' AND '{mp1}' GROUP BY 1, 2),
    attributed AS (SELECT person_key, arg_max(node, lpad(n::VARCHAR, 4, '0') || last_visit || node) AS attributed_org
                   FROM qual GROUP BY 1),
    dx AS (SELECT person_key, "group", min(onset) AS onset FROM cond
           WHERE "group" IS NOT NULL AND clinical_status = 'active' AND onset <= '{mp1}' GROUP BY 1, 2),
    bpday AS (SELECT person_key, date, min(sys) AS sys, min(dia) AS dia, min(node) AS node FROM bp
              WHERE date BETWEEN '{mp0}' AND '{mp1}' AND enc_class NOT IN ('EMER', 'IMP') GROUP BY 1, 2),
    bplast AS (SELECT person_key, arg_max(sys, date) AS sys, arg_max(dia, date) AS dia,
                      arg_max(node, date) AS bp_node, max(date) AS bp_date FROM bpday GROUP BY 1),
    a1cday AS (SELECT person_key, date, min(value_pct) AS v FROM a1c
               WHERE date BETWEEN '{mp0}' AND '{mp1}' AND value_pct IS NOT NULL GROUP BY 1, 2),
    a1clast AS (SELECT person_key, arg_max(v, date) AS a1c, max(date) AS a1c_date FROM a1cday GROUP BY 1)
    SELECT p.*, a.attributed_org,
      date_part('year', age(DATE '{mp1}', p.birth_date::DATE)) AS age,
      h.onset AS htn_onset, d.onset AS dm_onset, e.onset AS esrd_onset,
      b.sys, b.dia, b.bp_node, b.bp_date, g.a1c, g.a1c_date
    FROM person p
    JOIN attributed a USING (person_key)
    LEFT JOIN dx h ON h.person_key = p.person_key AND h."group" = 'htn'
    LEFT JOIN dx d ON d.person_key = p.person_key AND d."group" = 'dm'
    LEFT JOIN dx e ON e.person_key = p.person_key AND e."group" = 'esrd'
    LEFT JOIN bplast b ON b.person_key = p.person_key
    LEFT JOIN a1clast g ON g.person_key = p.person_key
    ORDER BY p.person_key
    """
    df = con.execute(sql).df()
    return add_flags(df)


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["age"] = df["age"].astype(int)
    df["age_group"] = pd.cut(
        df["age"], [-1, 17, 44, 64, 200], labels=["0-17", "18-44", "45-64", "65+"]
    ).astype(str)
    df["adult"] = df["age"] >= 18
    df["htn"] = df["adult"] & df["htn_onset"].notna()
    df["dm"] = df["adult"] & df["dm_onset"].notna()

    def b(x):  # nullable comparisons -> plain bool (missing value = False)
        return x.fillna(False).astype(bool)

    df["cbp_ip"] = df["age"].between(18, 85) & b(
        df["htn_onset"].notna() & (df["htn_onset"] <= CBP_ONSET_CUTOFF)
    )
    df["cbp_excl"] = df["cbp_ip"] & df["esrd_onset"].notna()
    df["cbp_den"] = df["cbp_ip"] & ~df["cbp_excl"]
    df["cbp_num"] = df["cbp_den"] & b((df["sys"] < 140) & (df["dia"] < 90))
    df["gsd_den"] = df["age"].between(18, 75) & df["dm_onset"].notna()
    df["gsd_num"] = df["gsd_den"] & (df["a1c"].isna() | b(df["a1c"] > 9.0))
    df["gsd_missing"] = df["gsd_den"] & df["a1c"].isna()
    for c in ("sex", "county", "rurality"):
        df[c] = df[c].fillna("Unknown")
    df["sex"] = df["sex"].replace({"female": "Female", "male": "Male", "unknown": "Unknown"})
    return df


MEASURES = {
    "htn_prevalence": ("Hypertension prevalence", "htn", "adult"),
    "dm_prevalence": ("Diabetes prevalence", "dm", "adult"),
    "cbp": ("Controlling high BP (<140/90), CMS165v13-adapted", "cbp_num", "cbp_den"),
    "gsd_gt9": ("HbA1c >9% or missing (inverse), CMS122v13-adapted", "gsd_num", "gsd_den"),
}


def rates(df: pd.DataFrame) -> dict:
    out = {}
    for k, (_, num, den) in MEASURES.items():
        n, d = int(df[num].sum()), int(df[den].sum())
        out[k] = {"numerator": n, "denominator": d, "rate": round(n / d, 4) if d else None}
    return out


def stratified(df: pd.DataFrame, view_key: str, small_cell: int = 11) -> pd.DataFrame:
    rows = []
    strata = {
        "Overall": None,
        "Organization": "attributed_org",
        "Age group": "age_group",
        "Sex": "sex",
        "County": "county",
        "Rurality": "rurality",
    }
    for sname, col in strata.items():
        groups = [("All", df)] if col is None else sorted(df.groupby(col), key=lambda kv: str(kv[0]))
        for val, g in groups:
            if col == "age_group" and val == "0-17":
                continue
            for k, r in rates(g).items():
                rows.append(
                    {
                        "view": view_key,
                        "stratifier": sname,
                        "stratum": str(val),
                        "measure": k,
                        "measure_label": MEASURES[k][0],
                        **r,
                        "small_cell": bool(r["numerator"] < small_cell or r["denominator"] < 30),
                    }
                )
    return pd.DataFrame(rows)

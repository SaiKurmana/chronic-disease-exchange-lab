"""Per-node data-quality report on what the health department actually received.

Dimensions: completeness, validity / conformance, timeliness, and uniqueness (duplicate resends).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median

import pandas as pd

from labcore import codes as C
from labcore.io import read_ndjson
from labcore.validate import structural_errors, us_core_errors

STANDARD_DX = {C.SNOMED, C.ICD10CM}
METRIC_LABELS = {
    "patients": "Patients received",
    "race_complete_pct": "Race recorded (%)",
    "ethnicity_complete_pct": "Ethnicity recorded (%)",
    "sex_known_pct": "Administrative sex known (%)",
    "county_complete_pct": "County (address.district) recorded (%)",
    "obs_effective_complete_pct": "Observations with effective date (%)",
    "condition_status_complete_pct": "Conditions with clinicalStatus (%)",
    "dx_standard_code_pct": "Chronic dx coded in SNOMED CT / ICD-10-CM (%)",
    "a1c_loinc_pct": "HbA1c results with LOINC code (%)",
    "bp_ucum_pct": "BP values in UCUM mm[Hg] (%)",
    "med_rxnorm_pct": "Medications coded in RxNorm (%)",
    "bp_plausible_pct": "BP values physiologically plausible (%)",
    "fhir_structural_valid_pct": "Resources passing FHIR R4(B) structural validation (%)",
    "us_core_conformant_pct": "Profiled resources meeting US Core 'must have' (%)",
    "median_lag_days": "Median days from clinical event to availability",
    "within_7_days_pct": "Records available within 7 days (%)",
    "pending_at_extract": "Records not yet loaded at extract date",
    "duplicate_bp_resends": "Duplicate BP resends",
}


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def node_quality(node: str, received_dir: Path, pending: int = 0, validate: bool = True) -> dict:
    get = {
        t: read_ndjson(received_dir / node / f"{t}.ndjson")
        for t in ("Patient", "Encounter", "Condition", "Observation", "MedicationRequest")
    }
    pats, conds, obs, meds = get["Patient"], get["Condition"], get["Observation"], get["MedicationRequest"]
    exts = [{e["url"] for e in p.get("extension", [])} for p in pats]
    bp_vals, bp_ucum, bp_total, a1c_total, a1c_loinc = [], 0, 0, 0, 0
    dup = Counter()
    lags = []
    for o in obs:
        codes = {(c.get("system"), c.get("code")) for c in o.get("code", {}).get("coding", [])}
        eff = o.get("effectiveDateTime")
        lu = o.get("meta", {}).get("lastUpdated")
        if eff and lu:
            lags.append((date.fromisoformat(lu[:10]) - date.fromisoformat(eff[:10])).days)
        qs = [c.get("valueQuantity") for c in o.get("component", [])] or [o.get("valueQuantity")]
        if codes & {C.BP_PANEL[:2], C.SYSTOLIC[:2], C.DIASTOLIC[:2]}:
            for q in qs:
                if q:
                    bp_total += 1
                    bp_ucum += int(q.get("system") == C.UCUM and q.get("code") == "mm[Hg]")
            if C.BP_PANEL[:2] in codes and len(qs) == 2 and all(qs):
                bp_vals.append((qs[0]["value"], qs[1]["value"]))
                if eff:
                    dup[(o["subject"]["reference"], eff, qs[0]["value"], qs[1]["value"])] += 1
            elif len(qs) == 1 and qs[0]:
                bp_vals.append((qs[0]["value"],))
        else:
            a1c_total += 1
            a1c_loinc += int(any(s == C.LOINC for s, _ in codes))
    plausible = sum(
        1
        for v in bp_vals
        if (len(v) == 2 and 60 <= v[0] <= 260 and 30 <= v[1] <= 160 and v[0] > v[1])
        or (len(v) == 1 and 30 <= v[0] <= 260)
    )
    struct_ok = us_ok = profiled = 0
    all_res = [r for t in get.values() for r in t]
    if validate:
        for r in all_res:
            struct_ok += int(not structural_errors(r))
            if r.get("meta", {}).get("profile"):
                profiled += 1
                us_ok += int(not us_core_errors(r))
    return {
        "node": node,
        "patients": len(pats),
        "race_complete_pct": _pct(sum(C.US_CORE_RACE in e for e in exts), len(pats)),
        "ethnicity_complete_pct": _pct(sum(C.US_CORE_ETHNICITY in e for e in exts), len(pats)),
        "sex_known_pct": _pct(sum(p.get("gender") in ("male", "female") for p in pats), len(pats)),
        "county_complete_pct": _pct(
            sum(bool((p.get("address") or [{}])[0].get("district")) for p in pats), len(pats)
        ),
        "obs_effective_complete_pct": _pct(sum(bool(o.get("effectiveDateTime")) for o in obs), len(obs)),
        "condition_status_complete_pct": _pct(sum("clinicalStatus" in c for c in conds), len(conds)),
        "dx_standard_code_pct": _pct(
            sum(any(c.get("system") in STANDARD_DX for c in x["code"].get("coding", [])) for x in conds),
            len(conds),
        ),
        "a1c_loinc_pct": _pct(a1c_loinc, a1c_total),
        "bp_ucum_pct": _pct(bp_ucum, bp_total),
        "med_rxnorm_pct": _pct(
            sum(
                any(
                    c.get("system") == C.RXNORM
                    for c in m.get("medicationCodeableConcept", {}).get("coding", [])
                )
                for m in meds
            ),
            len(meds),
        ),
        "bp_plausible_pct": _pct(plausible, len(bp_vals)),
        "fhir_structural_valid_pct": _pct(struct_ok, len(all_res)) if validate else None,
        "us_core_conformant_pct": _pct(us_ok, profiled) if validate else None,
        "median_lag_days": float(median(lags)) if lags else None,
        "within_7_days_pct": _pct(sum(x <= 7 for x in lags), len(lags)),
        "pending_at_extract": int(pending),
        "duplicate_bp_resends": int(sum(n - 1 for n in dup.values() if n > 1)),
    }


def quality_report(received_dir: Path, pending: dict[str, int], validate: bool = True) -> pd.DataFrame:
    nodes = sorted(p.name for p in received_dir.iterdir() if p.is_dir())
    return pd.DataFrame([node_quality(n, received_dir, pending.get(n, 0), validate) for n in nodes])

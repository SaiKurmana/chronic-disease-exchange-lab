"""Normalize received FHIR (NDJSON) into analysis tables aligned to US Core / USCDI v3 elements.

Two modes make the value of terminology work visible:
  * map_codes=False -- "as received": only standard codes (SNOMED CT, ICD-10-CM, LOINC, RxNorm)
    and UCUM units are recognized; local codes, IFCC-unit lab results, free-text medications and
    non-UCUM units are left unrecognized.
  * map_codes=True  -- apply the receiver-maintained crosswalk (exchange/mappings/local_code_map.csv),
    IFCC->NGSP unit conversion, and unit-string normalization.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcore import codes as C
from labcore.io import read_csv
from network.policy import LINKAGE_EXT
from synth.orgs import COUNTY_BY_NAME, ZIP_TO_COUNTY

MAP_FILE = Path(__file__).parent / "mappings" / "local_code_map.csv"

GROUP_BY_CODE = {
    C.HTN_SNOMED[:2]: "htn",
    C.HTN_ICD[:2]: "htn",
    C.T2DM_SNOMED[:2]: "dm",
    C.T1DM_SNOMED[:2]: "dm",
    C.T2DM_ICD[:2]: "dm",
    C.T2DM_HYPER_ICD[:2]: "dm",
    C.T1DM_ICD[:2]: "dm",
    C.ESRD_SNOMED[:2]: "esrd",
    C.ESRD_ICD[:2]: "esrd",
}
A1C_CODES = {C.HBA1C[:2], C.HBA1C_HPLC[:2]}
MED_CLASS = {**{rx: "htn" for rx, _ in C.MEDS_HTN}, **{rx: "dm" for rx, _ in C.MEDS_DM}}


@dataclass
class CodeMap:
    codes: dict[tuple[str, str], tuple[str, str, str]] = field(default_factory=dict)
    med_text: dict[str, str] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = MAP_FILE) -> CodeMap:
        df = read_csv(path, dtype=str).fillna("")
        m = cls()
        for r in df.to_dict("records"):
            if r["source_system"] == "text":
                m.med_text[r["source_code"].lower()] = r["target_code"]
            elif r["source_system"] == "unit":
                m.units[r["source_code"]] = r["target_code"]
            else:
                m.codes[(r["source_system"], r["source_code"])] = (
                    r["target_system"],
                    r["target_code"],
                    r["transform"],
                )
        return m


def _codings(cc: dict | None) -> list[tuple[str, str]]:
    return [(c.get("system"), c.get("code")) for c in (cc or {}).get("coding", [])]


def _ref_id(ref: dict | None) -> str:
    return (ref or {}).get("reference", "").split("/", 1)[-1]


@dataclass
class Tables:
    patients: pd.DataFrame
    encounters: pd.DataFrame
    conditions: pd.DataFrame
    bp: pd.DataFrame
    a1c: pd.DataFrame
    meds: pd.DataFrame
    stats: dict


def normalize(
    received: dict[str, dict[str, list[dict]]], map_codes: bool = True, code_map: CodeMap | None = None
) -> Tables:
    """`received[node][resourceType] -> list of FHIR resources` (after the broker's filter)."""
    cm = code_map or CodeMap.load()
    st: Counter = Counter()
    pats, encs, conds, bps, a1cs, meds = [], [], [], [], [], []
    for node in sorted(received):
        res = received[node]
        enc_class = {}
        for p in res.get("Patient", []):
            ext = {e["url"]: e for e in p.get("extension", [])}
            race = eth = None
            for url, key in ((C.US_CORE_RACE, "race"), (C.US_CORE_ETHNICITY, "eth")):
                if url in ext:
                    omb = [x for x in ext[url].get("extension", []) if x["url"] == "ombCategory"]
                    if omb:
                        if key == "race":
                            race = omb[0]["valueCoding"]["code"]
                        else:
                            eth = omb[0]["valueCoding"]["code"]
            toks = {x["url"]: x["valueString"] for x in ext.get(LINKAGE_EXT, {}).get("extension", [])}
            addr = (p.get("address") or [{}])[0]
            district = addr.get("district")
            county = district if district in COUNTY_BY_NAME else ZIP_TO_COUNTY.get(addr.get("postalCode", ""))
            if county and not district:
                st["county_derived_from_zip"] += 1
            pats.append(
                {
                    "node": node,
                    "patient_key": p["id"],
                    "birth_date": p.get("birthDate"),
                    "gender": p.get("gender") or "unknown",
                    "district": district,
                    "postal_code": addr.get("postalCode"),
                    "county": county,
                    "rurality": COUNTY_BY_NAME[county].rurality if county else None,
                    "race": race,
                    "ethnicity": eth,
                    **{k: toks.get(k) for k in ("T1", "T2", "T3", "T4", "T5")},
                }
            )
        for e in res.get("Encounter", []):
            cls = e.get("class", {}).get("code")
            enc_class[e["id"]] = cls
            encs.append(
                {
                    "node": node,
                    "patient_key": _ref_id(e.get("subject")),
                    "encounter_id": e["id"],
                    "date": e.get("period", {}).get("start", "")[:10],
                    "class": cls,
                    "last_updated": e.get("meta", {}).get("lastUpdated", "")[:10],
                }
            )
        for c in res.get("Condition", []):
            grp, mapped, sys_code = None, False, None
            for sc in _codings(c.get("code")):
                if sc in GROUP_BY_CODE:
                    grp, sys_code = GROUP_BY_CODE[sc], sc
                    break
            if grp is None and map_codes:
                for sc in _codings(c.get("code")):
                    if sc in cm.codes:
                        tgt = cm.codes[sc][:2]
                        grp, mapped, sys_code = GROUP_BY_CODE.get(tgt), True, sc
                        break
            st["conditions_total"] += 1
            st["conditions_mapped_from_local"] += int(mapped)
            st["conditions_unrecognized"] += int(grp is None)
            status = (c.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code")
            st["conditions_missing_clinical_status"] += int(status is None)
            conds.append(
                {
                    "node": node,
                    "patient_key": _ref_id(c.get("subject")),
                    "condition_id": c["id"],
                    "group": grp,
                    "source_system": sys_code[0] if sys_code else _codings(c.get("code"))[0][0],
                    "source_code": sys_code[1] if sys_code else _codings(c.get("code"))[0][1],
                    "mapped_from_local": mapped,
                    "onset": (c.get("onsetDateTime") or c.get("recordedDate", ""))[:10],
                    "clinical_status": status or "active",
                    "last_updated": c.get("meta", {}).get("lastUpdated", "")[:10],
                }
            )
        split: dict[tuple, dict] = {}
        seen_obs: set = set()
        for o in res.get("Observation", []):
            when = o.get("effectiveDateTime")
            if not when:
                st["obs_missing_effective"] += 1
                when = o.get("issued", "")  # fall back to issued (documented simplification)
            pk = _ref_id(o.get("subject"))
            ecls = enc_class.get(_ref_id(o.get("encounter")))
            lu = o.get("meta", {}).get("lastUpdated", "")[:10]
            codes = _codings(o.get("code"))
            if C.BP_PANEL[:2] in codes:
                vals, units = {}, set()
                for comp in o.get("component", []):
                    cc = _codings(comp.get("code"))
                    q = comp.get("valueQuantity") or {}
                    for target, name in ((C.SYSTOLIC[:2], "sys"), (C.DIASTOLIC[:2], "dia")):
                        if target in cc and "value" in q:
                            vals[name] = q["value"]
                            units.add((q.get("system"), q.get("code") or q.get("unit")))
                _add_bp(bps, st, cm, map_codes, node, pk, when, ecls, vals, units, "panel", lu, seen_obs)
            elif C.SYSTOLIC[:2] in codes or C.DIASTOLIC[:2] in codes:
                q = o.get("valueQuantity") or {}
                key = (pk, when, _ref_id(o.get("encounter")))
                d = split.setdefault(key, {"vals": {}, "units": set(), "ecls": ecls, "lu": lu})
                d["vals"]["sys" if C.SYSTOLIC[:2] in codes else "dia"] = q.get("value")
                d["units"].add((q.get("system"), q.get("code") or q.get("unit")))
                d["lu"] = max(d["lu"], lu)
            elif set(codes) & A1C_CODES:
                q = o.get("valueQuantity") or {}
                a1cs.append(
                    {
                        "node": node,
                        "patient_key": pk,
                        "datetime": when,
                        "date": when[:10],
                        "value_pct": q.get("value"),
                        "source_code": codes[0][1],
                        "converted": False,
                        "last_updated": lu,
                    }
                )
            elif map_codes and any(sc in cm.codes and cm.codes[sc][1] == "4548-4" for sc in codes):
                q = o.get("valueQuantity") or {}
                tf = next(cm.codes[sc][2] for sc in codes if sc in cm.codes)
                v = q.get("value")
                if tf == "ifcc_mmol_mol_to_ngsp_percent" and q.get("code") == "mmol/mol":
                    v = C.ifcc_to_ngsp(v)
                st["a1c_converted_ifcc"] += 1
                a1cs.append(
                    {
                        "node": node,
                        "patient_key": pk,
                        "datetime": when,
                        "date": when[:10],
                        "value_pct": v,
                        "source_code": codes[0][1],
                        "converted": True,
                        "last_updated": lu,
                    }
                )
            else:
                st["observations_unrecognized"] += 1
        for (pk, when, _enc), d in sorted(split.items()):
            st["bp_split_pairs"] += 1
            _add_bp(
                bps,
                st,
                cm,
                map_codes,
                node,
                pk,
                when,
                d["ecls"],
                d["vals"],
                d["units"],
                "split",
                d["lu"],
                seen_obs,
            )
        for m in res.get("MedicationRequest", []):
            med = m.get("medicationCodeableConcept", {})
            rx = next((c for s, c in _codings(med) if s == C.RXNORM), None)
            from_text = False
            if rx is None and map_codes and med.get("text", "").lower() in cm.med_text:
                rx, from_text = cm.med_text[med["text"].lower()], True
            st["meds_total"] += 1
            st["meds_mapped_from_text"] += int(from_text)
            st["meds_unrecognized"] += int(rx is None)
            meds.append(
                {
                    "node": node,
                    "patient_key": _ref_id(m.get("subject")),
                    "rxnorm": rx,
                    "med_class": MED_CLASS.get(rx),
                    "date": m.get("authoredOn", "")[:10],
                    "mapped_from_text": from_text,
                }
            )

    def df(rows, cols):
        return pd.DataFrame(rows, columns=cols) if not rows else pd.DataFrame(rows)

    return Tables(
        patients=df(pats, ["node", "patient_key"]),
        encounters=df(encs, ["node", "patient_key", "date", "class"]),
        conditions=df(conds, ["node", "patient_key", "group", "onset"]),
        bp=df(bps, ["node", "patient_key", "date", "sys", "dia", "enc_class"]),
        a1c=df(a1cs, ["node", "patient_key", "date", "value_pct"]),
        meds=df(meds, ["node", "patient_key", "rxnorm", "med_class"]),
        stats=dict(sorted(st.items())),
    )


def _add_bp(bps, st, cm, map_codes, node, pk, when, ecls, vals, units, style, lu, seen):
    if "sys" not in vals or "dia" not in vals or vals["sys"] is None or vals["dia"] is None:
        st["bp_incomplete"] += 1
        return
    ok_units = {(C.UCUM, "mm[Hg]")}
    unit_ok = units <= ok_units
    if not unit_ok and map_codes and all(u[1] in cm.units for u in units):
        unit_ok = True
        st["bp_unit_normalized"] += 1
    if not unit_ok:
        st["bp_unit_unrecognized"] += 1
        return
    key = (node, pk, when, vals["sys"], vals["dia"])
    if key in seen:  # identical resend (interface duplicate)
        st["bp_duplicate_resends_removed"] += 1
        return
    seen.add(key)
    bps.append(
        {
            "node": node,
            "patient_key": pk,
            "datetime": when,
            "date": when[:10],
            "sys": vals["sys"],
            "dia": vals["dia"],
            "enc_class": ecls or "AMB",
            "style": style,
            "last_updated": lu,
        }
    )

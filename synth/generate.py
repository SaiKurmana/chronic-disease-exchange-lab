"""Deterministic synthetic population + per-organization FHIR R4 records.

Pipeline:
  1. Draw ~N persons (ground truth): demographics, county, latent hypertension / diabetes /
     ESRD status, latent BP control and HbA1c level.
  2. Attach each person to a home organization and, for some, to 1-2 additional organizations
     (cross-organization care -> duplicate Patient records that must be resolved).
  3. Emit each organization's view as FHIR R4 resources (Patient, Encounter, Condition,
     Observation, MedicationRequest, Organization) using that organization's "EHR flavor":
     coding variations, local codes, missing fields, unit variants, timeliness lags.
  4. Write per-organization NDJSON (data/raw/<org>/<Type>.ndjson) and ground truth CSVs.

All randomness flows from a single integer seed via per-person string-seeded RNGs, so the
output is byte-for-byte reproducible.

Usage: python -m synth.generate [--n 5000] [--seed 20250101] [--out data]

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from labcore import codes as C
from labcore.config import DATA_AS_OF, DATA_DIR, HISTORY_START, MP_END, N_PERSONS, NS, SEED
from labcore.io import write_csv, write_ndjson

from . import names as NM
from .orgs import COUNTIES, ORG_BY_ID, ORGS, STATE, Org

END_OF_DATA = date(2025, 12, 31)


# ----------------------------------------------------------------------------------------------
# Ground-truth person model
# ----------------------------------------------------------------------------------------------
@dataclass
class Person:
    pid: str
    sex: str  # "male" | "female"
    given: str
    family: str
    birth_date: date
    county: str
    rurality: str
    zip: str
    city: str
    line: str
    phone: str
    race: str | None
    ethnicity: str
    true_htn: bool = False
    true_dm: bool = False
    dm_type: int = 0
    true_esrd: bool = False
    htn_dx: bool = False
    dm_dx: bool = False
    htn_onset: date | None = None
    dm_onset: date | None = None
    esrd_onset: date | None = None
    bp_controlled: bool = True
    a1c_mean: float = 5.4
    twin_of: str | None = None
    orgs: list[str] = field(default_factory=list)
    other_dx: list[int] = field(default_factory=list)


def age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def rand_date(rng: random.Random, start: date, end: date) -> date:
    if end < start:
        return start
    return start + timedelta(days=rng.randint(0, (end - start).days))


def weighted(rng: random.Random, items: dict):
    keys = list(items)
    return rng.choices(keys, weights=[items[k] for k in keys], k=1)[0]


def _race(rng: random.Random, rural: bool) -> str:
    if rural:
        dist = {"2106-3": 0.80, "2054-5": 0.06, "1002-5": 0.08, "2028-9": 0.04, "2076-8": 0.02}
    else:
        dist = {"2106-3": 0.55, "2054-5": 0.24, "2028-9": 0.13, "1002-5": 0.03, "2076-8": 0.05}
    return weighted(rng, dist)


def make_person(i: int, seed: int) -> Person:
    rng = random.Random(f"{seed}-person-{i}")
    county = rng.choices(COUNTIES, weights=[c.weight for c in COUNTIES], k=1)[0]
    rural = county.rurality == "Rural"
    sex = "female" if rng.random() < 0.51 else "male"
    band = weighted(rng, {(5, 17): 0.10, (18, 44): 0.38, (45, 64): 0.32, (65, 95): 0.20})
    age = rng.randint(*band)
    birth = date(MP_END.year - age, 1, 1) + timedelta(days=rng.randint(0, 364))
    given = rng.choice(NM.FEMALE if sex == "female" else NM.MALE)
    family = rng.choice(NM.FAMILY)
    eth = "2135-2" if rng.random() < (0.08 if rural else 0.16) else "2186-5"
    p = Person(
        pid=f"P{i:05d}",
        sex=sex,
        given=given,
        family=family,
        birth_date=birth,
        county=county.name,
        rurality=county.rurality,
        zip=rng.choice(county.zips),
        city=county.city,
        line=f"{rng.randint(10, 9899)} {rng.choice(NM.STREETS)} St",
        phone=f"000-555-01{rng.randint(0, 99):02d}",
        race=_race(rng, rural),
        ethnicity=eth,
    )
    _clinical(p, rng)
    return p


def _clinical(p: Person, rng: random.Random) -> None:
    age = age_on(p.birth_date, MP_END)
    rural = p.rurality == "Rural"
    black = p.race == "2054-5"
    hisp = p.ethnicity == "2135-2"
    if age < 18:
        htn_p, dm_p = 0.01, 0.003
    elif age < 45:
        htn_p, dm_p = 0.12, 0.04
    elif age < 65:
        htn_p, dm_p = 0.40, 0.14
    else:
        htn_p, dm_p = 0.62, 0.22
    htn_p *= (1.18 if black else 1.0) * (1.10 if rural else 1.0)
    p.true_htn = rng.random() < min(htn_p, 0.9)
    dm_p = dm_p * (1.3 if (black or hisp) else 1.0) * (1.15 if rural else 1.0) + (0.06 if p.true_htn else 0)
    p.true_dm = age >= 5 and rng.random() < min(dm_p, 0.6)
    if p.true_dm:
        p.dm_type = 1 if rng.random() < 0.07 else 2
    esrd_p = 0.04 if (p.true_dm and p.true_htn) else (0.004 if (p.true_dm or p.true_htn) else 0.0005)
    p.true_esrd = age >= 18 and rng.random() < esrd_p

    adult_start = p.birth_date + timedelta(days=365 * (18 if age >= 18 else 5))
    if p.true_htn:
        p.htn_dx = rng.random() < (0.72 if rural else 0.83)
        # Mostly long-standing; some diagnosed during 2025 (incl. after June 30 -> outside CMS165 IP).
        if rng.random() < 0.08:
            p.htn_onset = rand_date(rng, date(2025, 1, 1), date(2025, 11, 30))
        else:
            p.htn_onset = rand_date(rng, max(adult_start, date(2005, 1, 1)), date(2024, 12, 31))
        base = 0.66 - (0.08 if rural else 0) - (0.05 if black else 0)
        p.bp_controlled = rng.random() < (base if p.htn_dx else 0.35)
    if p.true_dm:
        p.dm_dx = rng.random() < 0.88
        if rng.random() < 0.06:
            p.dm_onset = rand_date(rng, date(2025, 1, 1), date(2025, 10, 31))
        else:
            p.dm_onset = rand_date(rng, max(adult_start, date(2008, 1, 1)), date(2024, 12, 31))
        p.a1c_mean = min(13.5, max(5.6, rng.gauss(7.7 + (0.3 if rural else 0) + (0.3 if hisp else 0), 1.35)))
    else:
        p.a1c_mean = min(6.4, max(4.6, rng.gauss(5.4, 0.35)))
    if p.true_esrd:
        p.esrd_onset = rand_date(rng, date(2015, 1, 1), date(2025, 9, 30))
    if rng.random() < 0.22:
        p.other_dx.append(rng.randrange(3))  # an acute respiratory condition
    if rng.random() < 0.08:
        p.other_dx.append(3)  # major depressive disorder (sensitive; not minimum necessary for PH)


def assign_orgs(p: Person, rng: random.Random) -> None:
    county = next(c for c in COUNTIES if c.name == p.county)
    home = weighted(rng, county.home_orgs)
    p.orgs = [home]
    chronic = p.true_htn or p.true_dm
    if rng.random() < (0.22 if chronic else 0.09):
        others = [o.id for o in ORGS if o.id != home]
        w = {o: (3.0 if o == "amc" else (1.5 if o in county.home_orgs else 0.4)) for o in others}
        p.orgs.append(weighted(rng, w))
        if rng.random() < 0.15:
            rest = [o for o in others if o not in p.orgs]
            p.orgs.append(rng.choice(rest))


# ----------------------------------------------------------------------------------------------
# Demographic variation at secondary organizations (what makes record linkage hard)
# ----------------------------------------------------------------------------------------------
def _typo(rng: random.Random, s: str) -> str:
    if len(s) < 4:
        return s
    i = rng.randint(1, len(s) - 2)
    if rng.random() < 0.5:
        return s[:i] + s[i + 1] + s[i] + s[i + 2 :]
    return s[:i] + s[i + 1 :]


def variant_demographics(p: Person, rng: random.Random) -> tuple[dict, list[str]]:
    d = {
        "given": p.given,
        "family": p.family,
        "birth_date": p.birth_date,
        "zip": p.zip,
        "county": p.county,
        "city": p.city,
        "line": p.line,
        "phone": p.phone,
    }
    applied: list[str] = []
    if p.given in NM.NICKNAMES and rng.random() < 0.30:
        d["given"] = NM.NICKNAMES[p.given]
        applied.append("nickname")
    if rng.random() < 0.08:
        d["family"] = _typo(rng, p.family)
        applied.append("family_typo")
    elif rng.random() < 0.04:
        d["family"] = f"{p.family}-{rng.choice(NM.FAMILY)}"
        applied.append("hyphenated")
    if rng.random() < 0.10:
        c = rng.choice(COUNTIES)
        d.update(
            zip=rng.choice(c.zips),
            county=c.name,
            city=c.city,
            line=f"{rng.randint(10, 9899)} {rng.choice(NM.STREETS)} St",
        )
        applied.append("moved")
    if p.birth_date.day <= 12 and p.birth_date.day != p.birth_date.month and rng.random() < 0.03:
        d["birth_date"] = date(p.birth_date.year, p.birth_date.day, p.birth_date.month)
        applied.append("dob_day_month_swap")
    return d, applied


# ----------------------------------------------------------------------------------------------
# FHIR resource builders
# ----------------------------------------------------------------------------------------------
def _meta(org: Org, profile: str | None, last_updated: datetime) -> dict:
    m = {
        "lastUpdated": last_updated.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": f"{NS}/node/{org.id}",
        "tag": [dict(C.SYNTHETIC_TAG)],
        "security": [dict(C.HTEST_SECURITY)],
    }
    if profile:
        m["profile"] = [profile]
    return m


def _dt(d: date, hour: int = 9, minute: int = 0) -> str:
    return datetime.combine(d, time(hour, minute), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class OrgWriter:
    """Accumulates one organization's FHIR resources with its EHR flavor applied."""

    def __init__(self, org: Org, seed: int):
        self.org = org
        self.f = org.flavor
        self.seed = seed
        self.res: dict[str, list[dict]] = {
            t: []
            for t in ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest", "Organization"]
        }
        self.counter = 0

    def nid(self, prefix: str) -> str:
        self.counter += 1
        return f"{self.org.id}-{prefix}-{self.counter:06d}"

    def last_updated(self, rng: random.Random, effective: date) -> datetime:
        lo, hi = self.f.lag_days
        lag = rng.randint(lo, hi)
        if self.f.batch_monthly:
            # monthly batch: loaded after the end of the month, plus processing days
            nxt = date(effective.year + (effective.month == 12), effective.month % 12 + 1, 1)
            d = nxt + timedelta(days=lag)
        else:
            d = effective + timedelta(days=lag)
        return datetime.combine(d, time(23, 0), tzinfo=UTC)

    # -- Organization ---------------------------------------------------------------------------
    def organization(self) -> None:
        o = self.org
        self.res["Organization"].append(
            {
                "resourceType": "Organization",
                "id": o.id,
                "meta": _meta(o, C.PROFILE["Organization"], datetime(2024, 1, 1, tzinfo=UTC)),
                "identifier": [{"system": f"{NS}/sid/organization", "value": o.id}],
                "active": True,
                "name": o.name,
                "type": [{"text": o.kind}],
                "address": [{"district": o.county, "state": STATE, "country": "US"}],
            }
        )

    # -- Patient --------------------------------------------------------------------------------
    def patient(self, p: Person, pat_id: str, demo: dict, rng: random.Random) -> dict:
        f = self.f
        gender = "unknown" if rng.random() < f.unknown_gender else p.sex
        ext = []
        if p.race and rng.random() >= f.missing_race:
            ext.append(
                {
                    "url": C.US_CORE_RACE,
                    "extension": [
                        {
                            "url": "ombCategory",
                            "valueCoding": {
                                "system": C.CDC_RACE_ETH,
                                "code": p.race,
                                "display": C.RACE[p.race],
                            },
                        },
                        {"url": "text", "valueString": C.RACE[p.race]},
                    ],
                }
            )
        if rng.random() >= f.missing_ethnicity:
            ext.append(
                {
                    "url": C.US_CORE_ETHNICITY,
                    "extension": [
                        {
                            "url": "ombCategory",
                            "valueCoding": {
                                "system": C.CDC_RACE_ETH,
                                "code": p.ethnicity,
                                "display": C.ETHNICITY[p.ethnicity],
                            },
                        },
                        {"url": "text", "valueString": C.ETHNICITY[p.ethnicity]},
                    ],
                }
            )
        addr = {
            "use": "home",
            "line": [demo["line"]],
            "city": demo["city"],
            "state": STATE,
            "postalCode": demo["zip"],
            "country": "US",
        }
        if rng.random() >= f.missing_district:
            addr["district"] = demo["county"]
        mrn = f"{self.org.id.upper()}{rng.randint(1000000, 9999999)}"
        res = {
            "resourceType": "Patient",
            "id": pat_id,
            "meta": _meta(self.org, C.PROFILE["Patient"], datetime(2024, 1, 1, tzinfo=UTC)),
            "extension": ext,
            "identifier": [
                {
                    "use": "usual",
                    "type": {
                        "coding": [{"system": C.V2_0203, "code": "MR", "display": "Medical record number"}]
                    },
                    "system": f"{NS}/sid/{self.org.id}-mrn",
                    "value": mrn,
                }
            ],
            "name": [{"use": "official", "family": demo["family"], "given": [demo["given"]]}],
            "gender": gender,
            "birthDate": demo["birth_date"].isoformat(),
            "address": [addr],
        }
        if rng.random() >= f.missing_phone:
            res["telecom"] = [{"system": "phone", "value": demo["phone"], "use": "home"}]
        if not ext:
            del res["extension"]
        self.res["Patient"].append(res)
        return res

    # -- Encounter ------------------------------------------------------------------------------
    def encounter(self, pat_id: str, d: date, kind: str, rng: random.Random) -> dict:
        cls = {"AMB": C.CLASS_AMB, "EMER": C.CLASS_EMER, "IMP": C.CLASS_IMP}[kind]
        etype = (
            C.ENC_ED if kind in ("EMER", "IMP") else (C.ENC_CHECKUP if rng.random() < 0.4 else C.ENC_FOLLOWUP)
        )
        end = d + timedelta(days=rng.randint(1, 4)) if kind == "IMP" else d
        res = {
            "resourceType": "Encounter",
            "id": self.nid("enc"),
            "meta": _meta(self.org, C.PROFILE["Encounter"], self.last_updated(rng, end)),
            "status": "finished",
            "class": C.coding(cls),
            "type": [{"coding": [C.coding(etype)], "text": etype[2]}],
            "subject": {"reference": f"Patient/{pat_id}"},
            "period": {"start": _dt(d, 9), "end": _dt(end, 10)},
            "serviceProvider": {"reference": f"Organization/{self.org.id}", "display": self.org.name},
        }
        self.res["Encounter"].append(res)
        return res

    # -- Condition ------------------------------------------------------------------------------
    def _dx_code(self, which: str, p: Person, rng: random.Random) -> dict:
        f = self.f
        snomed = {
            "htn": C.HTN_SNOMED,
            "dm": C.T1DM_SNOMED if p.dm_type == 1 else C.T2DM_SNOMED,
            "esrd": C.ESRD_SNOMED,
        }[which]
        if which == "dm":
            icd = C.T1DM_ICD if p.dm_type == 1 else (C.T2DM_HYPER_ICD if p.a1c_mean > 9 else C.T2DM_ICD)
        else:
            icd = {"htn": C.HTN_ICD, "esrd": C.ESRD_ICD}[which]
        local = {
            "htn": ("HTN", "Hypertension (local)"),
            "dm": ("DM2", "Diabetes (local)"),
            "esrd": ("ESRD", "Kidney failure on dialysis (local)"),
        }[which]
        style = f.dx_coding
        if style == "icd|snomed":
            style = "icd" if rng.random() < f.icd_rate else "snomed"
        if style == "local":
            if rng.random() < f.local_dx_rate:
                return {
                    "coding": [{"system": C.LOCAL_DX_RHC, "code": local[0], "display": local[1]}],
                    "text": local[1],
                }
            style = "snomed"
        if style == "snomed+icd":
            return {"coding": [C.coding(snomed), C.coding(icd)], "text": snomed[2]}
        if style == "icd":
            return {"coding": [C.coding(icd)], "text": icd[2]}
        return {"coding": [C.coding(snomed)], "text": snomed[2]}

    def condition(
        self,
        pat_id: str,
        code: dict,
        onset: date,
        recorded: date,
        rng: random.Random,
        enc_id: str | None = None,
    ) -> dict:
        res = {
            "resourceType": "Condition",
            "id": self.nid("cond"),
            "meta": _meta(self.org, C.PROFILE["Condition"], self.last_updated(rng, recorded)),
            "clinicalStatus": {"coding": [{"system": C.COND_CLINICAL, "code": "active"}]},
            "verificationStatus": {"coding": [{"system": C.COND_VER, "code": "confirmed"}]},
            "category": [
                {
                    "coding": [
                        {
                            "system": C.COND_CATEGORY,
                            "code": "problem-list-item",
                            "display": "Problem List Item",
                        }
                    ]
                }
            ],
            "code": code,
            "subject": {"reference": f"Patient/{pat_id}"},
            "onsetDateTime": onset.isoformat(),
            "recordedDate": recorded.isoformat(),
        }
        if enc_id:
            res["encounter"] = {"reference": f"Encounter/{enc_id}"}
        if rng.random() < self.f.missing_clinical_status:
            del res["clinicalStatus"]
        self.res["Condition"].append(res)
        return res

    # -- Observations ---------------------------------------------------------------------------
    def _obs_base(
        self,
        pat_id: str,
        enc_id: str,
        d: date,
        hour: int,
        minute: int,
        profile: str,
        category: str,
        rng: random.Random,
    ) -> dict:
        res = {
            "resourceType": "Observation",
            "id": self.nid("obs"),
            "meta": _meta(self.org, profile, self.last_updated(rng, d)),
            "status": "final",
            "category": [{"coding": [{"system": C.OBS_CATEGORY, "code": category}]}],
            "subject": {"reference": f"Patient/{pat_id}"},
            "encounter": {"reference": f"Encounter/{enc_id}"},
            "effectiveDateTime": _dt(d, hour, minute),
            "issued": _dt(d, hour, minute + 5),
        }
        if rng.random() < self.f.missing_effective:
            del res["effectiveDateTime"]
        return res

    def _qty(self, v: float, unit: str) -> dict:
        q = {"value": v, "unit": unit}
        if unit in ("mm[Hg]", "%", "kg", "kg/m2", "mmol/mol"):
            q.update(system=C.UCUM, code=unit)
        return q

    def bp(
        self, pat_id: str, enc_id: str, d: date, sbp: int, dbp: int, minute: int, rng: random.Random
    ) -> None:
        f = self.f
        unit = f.bp_unit
        if f.bp_style == "panel":
            res = self._obs_base(pat_id, enc_id, d, 9, minute, C.PROFILE["BloodPressure"], "vital-signs", rng)
            res["code"] = {"coding": [C.coding(C.BP_PANEL)], "text": "Blood pressure"}
            res["component"] = [
                {"code": {"coding": [C.coding(C.SYSTOLIC)]}, "valueQuantity": self._qty(sbp, unit)},
                {"code": {"coding": [C.coding(C.DIASTOLIC)]}, "valueQuantity": self._qty(dbp, unit)},
            ]
            self.res["Observation"].append(res)
            if rng.random() < f.duplicate_obs_rate:
                dup = dict(res, id=self.nid("obs"))
                self.res["Observation"].append(dup)
        else:
            for code, val in ((C.SYSTOLIC, sbp), (C.DIASTOLIC, dbp)):
                res = self._obs_base(pat_id, enc_id, d, 9, minute, None, "vital-signs", rng)
                res["code"] = {"coding": [C.coding(code)], "text": code[2]}
                res["valueQuantity"] = self._qty(val, unit)
                self.res["Observation"].append(res)

    def a1c(self, pat_id: str, enc_id: str, d: date, pct: float, rng: random.Random) -> None:
        f = self.f
        res = self._obs_base(pat_id, enc_id, d, 10, 0, C.PROFILE["Lab"], "laboratory", rng)
        if f.a1c_style == "ifcc-local" and rng.random() < f.a1c_ifcc_rate:
            res["code"] = {
                "coding": [
                    {"system": C.LOCAL_LAB_FQHC, "code": "A1C-IFCC", "display": "HbA1c (IFCC, point of care)"}
                ],
                "text": "HbA1c IFCC",
            }
            res["valueQuantity"] = self._qty(C.ngsp_to_ifcc(pct), "mmol/mol")
        elif f.a1c_style == "17856-6":
            res["code"] = {"coding": [C.coding(C.HBA1C_HPLC)], "text": "Hemoglobin A1c"}
            res["valueQuantity"] = self._qty(pct, "%")
        else:
            res["code"] = {"coding": [C.coding(C.HBA1C)], "text": "Hemoglobin A1c"}
            res["valueQuantity"] = self._qty(pct, "%")
        self.res["Observation"].append(res)

    def weight(self, pat_id: str, enc_id: str, d: date, kg: float, rng: random.Random) -> None:
        res = self._obs_base(pat_id, enc_id, d, 9, 2, None, "vital-signs", rng)
        res["code"] = {"coding": [C.coding(C.BODY_WEIGHT)], "text": "Body weight"}
        res["valueQuantity"] = self._qty(kg, "kg")
        self.res["Observation"].append(res)

    # -- MedicationRequest ----------------------------------------------------------------------
    def med(
        self, pat_id: str, enc_id: str, d: date, rx: tuple[str, str], reason: dict, rng: random.Random
    ) -> None:
        res = {
            "resourceType": "MedicationRequest",
            "id": self.nid("medrx"),
            "meta": _meta(self.org, C.PROFILE["MedicationRequest"], self.last_updated(rng, d)),
            "status": "active",
            "intent": "order",
            "subject": {"reference": f"Patient/{pat_id}"},
            "encounter": {"reference": f"Encounter/{enc_id}"},
            "authoredOn": d.isoformat(),
            "reasonCode": [reason],
            "dosageInstruction": [{"text": "Take 1 tablet by mouth daily"}],
        }
        if rng.random() < self.f.med_text_only:
            # free-text medication, e.g. "Lisinopril 10mg tablet" -- needs text-to-RxNorm mapping
            res["medicationCodeableConcept"] = {"text": C.MED_FREE_TEXT[rx[0]]}
        else:
            res["medicationCodeableConcept"] = {
                "coding": [{"system": C.RXNORM, "code": rx[0], "display": rx[1]}],
                "text": rx[1],
            }
        self.res["MedicationRequest"].append(res)


# ----------------------------------------------------------------------------------------------
# Per-(person, organization) clinical history
# ----------------------------------------------------------------------------------------------
def _visit_dates(rng: random.Random, n_2024: int, n_2025: int) -> list[date]:
    ds = [rand_date(rng, HISTORY_START, date(2024, 12, 31)) for _ in range(n_2024)]
    ds += [rand_date(rng, date(2025, 1, 1), END_OF_DATA) for _ in range(n_2025)]
    return sorted(set(ds))


def _bp_reading(p: Person, rng: random.Random, org: Org, ed: bool) -> tuple[int, int]:
    if p.true_htn:
        controlled = p.bp_controlled
        if not controlled and rng.random() < max(0.0, org.flavor.bp_control_shift):
            controlled = True
        if controlled and rng.random() < max(0.0, -org.flavor.bp_control_shift):
            controlled = False
        ms, md = (127, 78) if controlled else (149, 91)
        s, dd = rng.gauss(ms, 7), rng.gauss(md, 6)
    else:
        s, dd = rng.gauss(117, 10), rng.gauss(74, 8)
    if ed:
        s, dd = s + rng.gauss(14, 6), dd + rng.gauss(6, 4)
    s = int(round(min(220, max(85, s))))
    dd = int(round(min(130, max(45, min(dd, s - 20)))))
    return s, dd


def build_org_history(
    p: Person, org: Org, role: str, w: OrgWriter, pat_id: str, rng: random.Random, demo: dict
) -> None:
    f = org.flavor
    w.patient(p, pat_id, demo, rng)
    chronic = p.true_htn or p.true_dm
    if role == "home":
        n24 = rng.randint(1, 3) + (1 if chronic else 0)
        n25 = 0 if rng.random() < 0.12 else rng.randint(1, 3) + (rng.randint(0, 2) if chronic else 0)
    else:
        n24 = rng.randint(0, 1)
        n25 = rng.randint(1, 2) if rng.random() < 0.85 else 0
    dates = _visit_dates(rng, n24, n25)
    if not dates:
        dates = [rand_date(rng, HISTORY_START, END_OF_DATA)]
    kinds = []
    for _ in dates:
        if role != "home" and f.ed_share and rng.random() < f.ed_share:
            kinds.append("IMP" if rng.random() < 0.2 else "EMER")
        else:
            kinds.append("AMB")
    encs = [w.encounter(pat_id, d, k, rng) for d, k in zip(dates, kinds, strict=True)]

    # Problem list: chronic diagnoses known to this organization.
    record_p = 0.93 if role == "home" else (0.35 if org.id == "amc" else 0.55)
    first = encs[0]
    first_d = dates[0]
    for which, flag, onset in (
        ("htn", p.htn_dx, p.htn_onset),
        ("dm", p.dm_dx, p.dm_onset),
        ("esrd", p.true_esrd, p.esrd_onset),
    ):
        if not flag or onset is None or onset > END_OF_DATA:
            continue
        if rng.random() >= record_p:
            continue
        # recorded at the first visit on/after onset (or first visit if onset predates the history)
        rec = next((d for d in dates if d >= onset), None)
        if rec is None:
            continue
        enc = encs[dates.index(rec)]
        w.condition(pat_id, w._dx_code(which, p, rng), onset, max(rec, first_d), rng, enc["id"])
    for k in p.other_dx:
        if rng.random() < 0.6:
            sn, icd = C.OTHER_CONDITIONS[k]
            code = (
                {"coding": [C.coding(icd)], "text": icd[2]}
                if f.dx_coding == "icd"
                else {"coding": [C.coding(sn)], "text": sn[2]}
            )
            w.condition(pat_id, code, first_d, first_d, rng, first["id"])

    # Vitals / labs / meds per encounter.
    a1c_this_year: dict[int, bool] = {}
    for d, k, enc in zip(dates, kinds, encs, strict=True):
        ed = k in ("EMER", "IMP")
        if rng.random() < (0.97 if not ed else 0.9):
            s, dd = _bp_reading(p, rng, org, ed)
            w.bp(pat_id, enc["id"], d, s, dd, 5, rng)
            if rng.random() < 0.15:  # repeat reading, typically a little lower
                w.bp(
                    pat_id,
                    enc["id"],
                    d,
                    max(85, s - rng.randint(2, 12)),
                    max(45, dd - rng.randint(0, 6)),
                    25,
                    rng,
                )
        if rng.random() < 0.5:
            w.weight(pat_id, enc["id"], d, round(rng.gauss(84, 16), 1), rng)
        if p.true_dm and not ed:
            yr = d.year
            if yr not in a1c_this_year:
                a1c_this_year[yr] = rng.random() >= f.a1c_test_miss
            if a1c_this_year[yr] and rng.random() < 0.75:
                v = rng.gauss(p.a1c_mean + f.a1c_shift, 0.45)
                w.a1c(pat_id, enc["id"], d, round(min(15.0, max(4.5, v)), 1), rng)
        elif not ed and rng.random() < 0.08:
            w.a1c(pat_id, enc["id"], d, round(rng.gauss(p.a1c_mean, 0.25), 1), rng)
        # Medications at the last ambulatory visit of each year
        is_last_of_year = d == max(x for x, kk in zip(dates, kinds, strict=True) if x.year == d.year)
        if not ed and is_last_of_year:
            if p.htn_dx and rng.random() < 0.75:
                for rx in rng.sample(C.MEDS_HTN, k=1 if rng.random() < 0.6 else 2):
                    w.med(pat_id, enc["id"], d, rx, w._dx_code("htn", p, rng), rng)
            if p.dm_dx and p.dm_type == 2 and rng.random() < 0.8:
                w.med(pat_id, enc["id"], d, C.MEDS_DM[0], w._dx_code("dm", p, rng), rng)
                if rng.random() < 0.25:
                    w.med(pat_id, enc["id"], d, C.MEDS_DM[1], w._dx_code("dm", p, rng), rng)


# ----------------------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------------------
def generate(n: int = N_PERSONS, seed: int = SEED, out: Path = DATA_DIR) -> dict:
    persons = [make_person(i, seed) for i in range(1, n + 1)]
    # Twins: same family name, DOB and address, different given names (a linkage precision trap).
    trng = random.Random(f"{seed}-twins")
    for i in sorted(trng.sample(range(0, n - 1, 2), k=max(1, n // 250))):
        a, b = persons[i], persons[i + 1]
        b.family, b.birth_date, b.zip, b.county, b.city, b.line, b.rurality = (
            a.family,
            a.birth_date,
            a.zip,
            a.county,
            a.city,
            a.line,
            a.rurality,
        )
        if b.given == a.given:
            b.given = "Kai" if a.given != "Kai" else "Mei"
        b.twin_of = a.pid
    for p in persons:
        assign_orgs(p, random.Random(f"{seed}-orgs-{p.pid}"))

    writers = {o.id: OrgWriter(o, seed) for o in ORGS}
    for w in writers.values():
        w.organization()
    # Patient ids are assigned from a per-org shuffled sequence so ids carry no cross-org signal.
    seqs = {}
    for o in ORGS:
        members = [p.pid for p in persons if o.id in p.orgs]
        order = list(range(1, len(members) + 1))
        random.Random(f"{seed}-ids-{o.id}").shuffle(order)
        seqs[o.id] = dict(zip(members, order, strict=True))

    links = []
    for p in persons:
        for k, org_id in enumerate(p.orgs):
            org = ORG_BY_ID[org_id]
            rng = random.Random(f"{seed}-hist-{p.pid}-{org_id}")
            pat_id = f"{org_id}-pt-{seqs[org_id][p.pid]:05d}"
            if k == 0:
                demo = {
                    "given": p.given,
                    "family": p.family,
                    "birth_date": p.birth_date,
                    "zip": p.zip,
                    "county": p.county,
                    "city": p.city,
                    "line": p.line,
                    "phone": p.phone,
                }
                applied = []
            else:
                demo, applied = variant_demographics(p, rng)
            build_org_history(p, org, "home" if k == 0 else "secondary", writers[org_id], pat_id, rng, demo)
            links.append(
                {
                    "person_id": p.pid,
                    "org_id": org_id,
                    "patient_id": pat_id,
                    "role": "home" if k == 0 else "secondary",
                    "variations": "|".join(applied),
                }
            )

    raw = out / "raw"
    counts = {}
    for org_id, w in writers.items():
        for rtype, rows in w.res.items():
            counts[f"{org_id}/{rtype}"] = write_ndjson(raw / org_id / f"{rtype}.ndjson", rows)

    gt = out / "ground_truth"
    pdf = pd.DataFrame(
        [
            {
                "person_id": p.pid,
                "sex": p.sex,
                "birth_date": p.birth_date.isoformat(),
                "age": age_on(p.birth_date, MP_END),
                "county": p.county,
                "rurality": p.rurality,
                "race": p.race,
                "ethnicity": p.ethnicity,
                "true_htn": p.true_htn,
                "htn_diagnosed": p.htn_dx,
                "htn_onset": p.htn_onset.isoformat() if p.htn_onset else "",
                "bp_controlled_latent": p.bp_controlled,
                "true_dm": p.true_dm,
                "dm_type": p.dm_type,
                "dm_diagnosed": p.dm_dx,
                "dm_onset": p.dm_onset.isoformat() if p.dm_onset else "",
                "a1c_latent_mean": round(p.a1c_mean, 2),
                "true_esrd": p.true_esrd,
                "n_orgs": len(p.orgs),
                "orgs": "|".join(p.orgs),
                "twin_of": p.twin_of or "",
            }
            for p in persons
        ]
    )
    write_csv(gt / "persons.csv", pdf)
    write_csv(gt / "links.csv", pd.DataFrame(links))
    return {"persons": n, "patient_records": len(links), "resources": counts, "as_of": DATA_AS_OF.isoformat()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=N_PERSONS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=DATA_DIR)
    a = ap.parse_args()
    summary = generate(a.n, a.seed, a.out)
    total = sum(summary["resources"].values())
    print(
        f"Generated {summary['persons']} persons -> {summary['patient_records']} patient records, "
        f"{total} FHIR resources across {len(ORGS)} organizations in {a.out}/raw (seed={a.seed})."
    )


if __name__ == "__main__":
    main()

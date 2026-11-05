"""Simulated geography, organizations, and per-organization "EHR flavors".

Everything here is fictional: the State of Lakeland, its counties, ZIP-like codes (000xx,
which are not assigned USPS ZIP codes), organizations, and code systems.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STATE = "LK"  # fictional "State of Lakeland" (not a real USPS abbreviation)
STATE_NAME = "Lakeland (fictional)"


@dataclass(frozen=True)
class County:
    name: str
    rurality: str  # "Urban" | "Rural"
    weight: float
    zips: tuple[str, ...]
    city: str
    # probability of home organization
    home_orgs: dict[str, float] = field(default_factory=dict)


COUNTIES: list[County] = [
    County(
        "Harbor County",
        "Urban",
        0.30,
        ("00101", "00102", "00103"),
        "Port Harbor",
        {"fqhc": 0.45, "amc": 0.35, "mmg": 0.20},
    ),
    County(
        "Mill County",
        "Urban",
        0.22,
        ("00201", "00202"),
        "Millbrook",
        {"mmg": 0.55, "fqhc": 0.20, "ipp": 0.15, "amc": 0.10},
    ),
    County(
        "Cedar County",
        "Urban",
        0.18,
        ("00301", "00302"),
        "Cedar Valley",
        {"ipp": 0.65, "mmg": 0.20, "amc": 0.15},
    ),
    County("Prairie County", "Rural", 0.12, ("00401",), "Prairie Junction", {"rhc": 0.80, "amc": 0.20}),
    County("Ridge County", "Rural", 0.10, ("00501",), "Ridgeview", {"rhc": 0.70, "mmg": 0.15, "amc": 0.15}),
    County("Lake County", "Rural", 0.08, ("00601",), "Lakeside", {"rhc": 0.75, "amc": 0.25}),
]
COUNTY_BY_NAME = {c.name: c for c in COUNTIES}
ZIP_TO_COUNTY = {z: c.name for c in COUNTIES for z in c.zips}


@dataclass(frozen=True)
class Flavor:
    """How an organization's EHR represents (or fails to represent) the same clinical facts."""

    dx_coding: str  # "snomed+icd" | "icd" | "snomed" | "local" | "icd|snomed"
    local_dx_rate: float = 0.0  # share of chronic dx carried only as a local code
    icd_rate: float = 1.0  # for "icd|snomed": share coded in ICD-10-CM (else SNOMED)
    bp_style: str = "panel"  # "panel" (85354-9 + components) | "split" (separate 8480-6 / 8462-4)
    bp_unit: str = "mm[Hg]"  # UCUM is "mm[Hg]"; "mmHg" is a common non-UCUM variant
    a1c_style: str = "4548-4"  # "4548-4" | "17856-6" | "ifcc-local"
    a1c_ifcc_rate: float = 0.0
    missing_race: float = 0.05
    missing_ethnicity: float = 0.05
    missing_district: float = 0.02  # county (address.district) not captured
    missing_phone: float = 0.05
    unknown_gender: float = 0.0
    missing_effective: float = 0.0  # observation has only `issued`, no effective[x]
    missing_clinical_status: float = 0.0
    duplicate_obs_rate: float = 0.0  # same reading sent twice under different ids
    med_text_only: float = 0.0  # medication as free text without RxNorm coding
    lag_days: tuple[int, int] = (0, 2)  # lastUpdated - effective (uniform range)
    batch_monthly: bool = False  # data loaded in monthly batches (timeliness)
    ed_share: float = 0.0  # share of secondary-org visits that are ED visits
    a1c_test_miss: float = 0.12  # prob. a diabetic patient has no HbA1c test in a year
    bp_control_shift: float = 0.0  # organization-level difference in BP control
    a1c_shift: float = 0.0  # organization-level difference in mean HbA1c


@dataclass(frozen=True)
class Org:
    id: str
    name: str
    kind: str
    county: str
    flavor: Flavor
    ehr_label: str  # descriptive "EHR flavor" label (no vendor names)


ORGS: list[Org] = [
    Org(
        "amc",
        "Lakeland Academic Medical Center",
        "Academic medical center",
        "Harbor County",
        Flavor(
            dx_coding="snomed+icd",
            bp_style="panel",
            a1c_style="4548-4",
            missing_race=0.04,
            missing_ethnicity=0.06,
            lag_days=(0, 1),
            ed_share=0.45,
            a1c_test_miss=0.08,
            bp_control_shift=0.04,
        ),
        "Enterprise EHR; SNOMED CT problem list with ICD-10-CM translations; BP panel",
    ),
    Org(
        "rhc",
        "Prairie Rural Health Clinic",
        "Rural health clinic",
        "Prairie County",
        Flavor(
            dx_coding="local",
            local_dx_rate=0.70,
            bp_style="split",
            a1c_style="4548-4",
            missing_race=0.35,
            missing_ethnicity=0.40,
            missing_district=0.30,
            missing_phone=0.10,
            lag_days=(3, 20),
            batch_monthly=True,
            a1c_test_miss=0.25,
            bp_control_shift=-0.08,
            a1c_shift=0.35,
        ),
        "Small-practice EHR; local problem codes; systolic/diastolic as separate observations; monthly batch",
    ),
    Org(
        "fqhc",
        "Harbor Community Health Center",
        "Federally qualified health center",
        "Harbor County",
        Flavor(
            dx_coding="icd",
            bp_style="panel",
            a1c_style="ifcc-local",
            a1c_ifcc_rate=0.60,
            missing_race=0.10,
            missing_ethnicity=0.05,
            missing_phone=0.15,
            unknown_gender=0.02,
            lag_days=(1, 5),
            a1c_test_miss=0.16,
            bp_control_shift=-0.06,
            a1c_shift=0.45,
        ),
        "Community health center EHR; ICD-10-CM only; point-of-care HbA1c in IFCC units (mmol/mol)",
    ),
    Org(
        "ipp",
        "Cedar Valley Family Practice",
        "Independent primary care practice",
        "Cedar County",
        Flavor(
            dx_coding="icd|snomed",
            icd_rate=0.70,
            bp_style="panel",
            bp_unit="mmHg",
            a1c_style="17856-6",
            missing_race=0.20,
            missing_ethnicity=0.22,
            missing_effective=0.12,
            med_text_only=0.40,
            lag_days=(2, 10),
            a1c_test_miss=0.12,
        ),
        "Ambulatory EHR; mixed ICD-10-CM/SNOMED CT; non-UCUM BP unit; free-text medications",
    ),
    Org(
        "mmg",
        "Millbrook Medical Group",
        "Multispecialty group",
        "Mill County",
        Flavor(
            dx_coding="snomed",
            bp_style="panel",
            a1c_style="4548-4",
            missing_race=0.12,
            missing_ethnicity=0.12,
            missing_clinical_status=0.15,
            duplicate_obs_rate=0.05,
            lag_days=(0, 3),
            a1c_test_miss=0.10,
            bp_control_shift=0.02,
        ),
        "Multi-site EHR; SNOMED CT only; occasional duplicate vitals from interface resends",
    ),
]
ORG_BY_ID = {o.id: o for o in ORGS}

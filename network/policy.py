"""Exchange-purpose policy and the minimum-necessary filter for the simulated network.

XP codes below are copied from the RCE "Exchange Purposes (XPs) SOP" v5.1 (effective
2026-08-03), Table 1. Which XPs this *simulated* network supports, and what each returns, is a
design choice of this portfolio project -- it is NOT a statement of TEFCA requirements.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date

from labcore import codes as C
from labcore.config import NS

# --- TEFCA Exchange Purpose codes (XP SOP v5.1, Table 1) -------------------------------------
XP_CODES: dict[str, str] = {
    "T-TREAT": "Treatment",
    "T-TRTMNT": "TEFCA Required Treatment",
    "T-PYMNT": "Payment",
    "T-HCO": "Health Care Operations",
    "T-HCO-CC": "Care Coordination/Case Management",
    "T-HCO-HED": "HEDIS Reporting",
    "T-HCO-QAI": "Quality Assessment and Improvement",
    "T-HCO-POP": "Population-Based Activities",
    "T-HCO-PTSAFETY": "Patient Safety",
    "T-HCO-PERF": "Performance Review",
    "T-PH": "Public Health",
    "T-PH-ECR": "Electronic Case Reporting",
    "T-PH-ELR": "Electronic Lab Reporting",
    "T-IAS": "Individual Access Services",
    "T-GOVDTRM": "Government Benefits Determination",
    "T-GOVDTRM-SSD": "Social Security Determination",
    "T-GOVDTRM-ACP": "Access Consent Policy",
}
# Per the XP SOP v5.1 Table 1, there are no Queries using these codes (push/message delivery only).
PUSH_ONLY = {"T-PH-ECR", "T-PH-ELR"}

# Who may assert which purpose in this simulation (mirrors XP SOP 4.3 examples and the Public
# Health XP Implementation SOP v1.1 section 4: only PHAs/Delegates may query under T-PH; only
# Health Care Providers may assert Treatment for a Query).
ROLE_FOR_PURPOSE = {"T-PH": {"PHA"}, "T-TREAT": {"HealthCareProvider"}}

# Operations each supported purpose may use under THIS use-case protocol.
OPERATIONS = {"T-PH": {"bulk-export"}, "T-TREAT": {"patient-query"}}

PH_RESOURCE_TYPES = ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest"]
FILTER_PROFILE_PH = "ph-chronic-disease-lds-v1"


@dataclass
class Decision:
    allowed: bool
    http_status: int
    reason: str
    issue_code: str = "processing"


def check_request(
    purpose: str,
    role: str,
    operation: str,
    *,
    jurisdiction: str | None,
    date_range: tuple[date, date] | None,
    types: list[str] | None = None,
) -> Decision:
    """Network-level checks performed by the broker before routing (deny-by-default)."""
    if purpose not in XP_CODES:
        return Decision(False, 400, f"Unknown exchange purpose code {purpose!r}", "code-invalid")
    if purpose in PUSH_ONLY:
        return Decision(
            False,
            400,
            f"{purpose} ({XP_CODES[purpose]}) is message delivery/push only; no Queries use this XP code",
            "not-supported",
        )
    if purpose not in OPERATIONS:
        return Decision(
            False,
            403,
            f"{purpose} ({XP_CODES[purpose]}) is a recognized XP code but is not "
            "supported by responders in this simulated network",
            "not-supported",
        )
    if role not in ROLE_FOR_PURPOSE[purpose]:
        return Decision(
            False,
            403,
            f"Requester role {role!r} may not assert {purpose}; requires {sorted(ROLE_FOR_PURPOSE[purpose])}",
            "forbidden",
        )
    if operation not in OPERATIONS[purpose]:
        return Decision(
            False,
            403,
            f"Operation {operation!r} is not permitted for {purpose} under this "
            f"use-case protocol (allowed: {sorted(OPERATIONS[purpose])})",
            "forbidden",
        )
    if purpose == "T-PH":
        if not jurisdiction:
            return Decision(False, 400, "Public Health requests must state the PHA jurisdiction", "required")
        if not date_range:
            return Decision(False, 400, "Public Health requests must include a date range", "required")
        if date_range[0] > date_range[1]:
            return Decision(False, 400, "Invalid date range", "value")
        bad = sorted(set(types or []) - set(PH_RESOURCE_TYPES))
        if bad:
            return Decision(
                False,
                403,
                f"Resource types {bad} exceed the minimum-necessary profile {FILTER_PROFILE_PH}",
                "forbidden",
            )
    return Decision(True, 200, "permitted")


# --- Minimum-necessary filter for Public Health (limited data set style) -----------------------
VS_CONDITIONS = {  # chronic disease value set (standard codes) used for filtering
    C.HTN_SNOMED[:2],
    C.HTN_ICD[:2],
    C.T2DM_SNOMED[:2],
    C.T1DM_SNOMED[:2],
    C.T2DM_ICD[:2],
    C.T2DM_HYPER_ICD[:2],
    C.T1DM_ICD[:2],
    C.ESRD_SNOMED[:2],
    C.ESRD_ICD[:2],
}
VS_OBSERVATIONS = {C.BP_PANEL[:2], C.SYSTOLIC[:2], C.DIASTOLIC[:2], C.HBA1C[:2], C.HBA1C_HPLC[:2]}
VS_MEDS = {(C.RXNORM, rx) for rx, _ in C.MEDS_HTN + C.MEDS_DM}
# Local codes the data sources registered with the network so filtering does not drop them.
# (Filtering keeps them; translating them to standard codes is the receiving PHA's job.)
REGISTERED_LOCAL = {
    (C.LOCAL_DX_RHC, "HTN"),
    (C.LOCAL_DX_RHC, "DM2"),
    (C.LOCAL_DX_RHC, "ESRD"),
    (C.LOCAL_LAB_FQHC, "A1C-IFCC"),
}
REGISTERED_MED_TEXT = {v.lower() for v in C.MED_FREE_TEXT.values()}

LINKAGE_EXT = f"{NS}/StructureDefinition/pprl-linkage-tokens"


def _codings(cc: dict | None) -> set[tuple[str, str]]:
    return {(c.get("system"), c.get("code")) for c in (cc or {}).get("coding", [])}


def _in(cc: dict | None, vs: set) -> bool:
    return bool(_codings(cc) & (vs | REGISTERED_LOCAL))


def _rdate(r: dict) -> str | None:
    t = r["resourceType"]
    if t == "Observation":
        return r.get("effectiveDateTime") or r.get("issued")
    if t == "Encounter":
        return r.get("period", {}).get("start")
    if t == "MedicationRequest":
        return r.get("authoredOn")
    if t == "Condition":
        return r.get("onsetDateTime") or r.get("recordedDate")
    return None


def ph_filter_resource(r: dict, start: date, end: date, pseudonym) -> tuple[dict | None, str]:
    """Return (filtered resource or None, reason). `pseudonym(patient_id)` maps ids to opaque ids."""
    t = r["resourceType"]
    if t not in PH_RESOURCE_TYPES:
        return None, "type-not-in-profile"
    d = _rdate(r)
    if t == "Condition":
        if not _in(r.get("code"), VS_CONDITIONS):
            return None, "condition-not-in-value-set"
        if d and d[:10] > end.isoformat():
            return None, "outside-date-range"
    elif (
        t in ("Observation", "Encounter", "MedicationRequest")
        and d
        and not (start.isoformat() <= d[:10] <= end.isoformat())
    ):
        return None, "outside-date-range"
    if t == "Observation" and not _in(r.get("code"), VS_OBSERVATIONS):
        return None, "observation-not-in-value-set"
    if t == "MedicationRequest":
        med = r.get("medicationCodeableConcept", {})
        if not (_in(med, VS_MEDS) or (med.get("text", "").lower() in REGISTERED_MED_TEXT)):
            return None, "medication-not-in-value-set"

    out = copy.deepcopy(r)
    out.pop("text", None)
    out.pop("note", None)
    if t == "Patient":
        out["id"] = pseudonym(r["id"])
        out["identifier"] = [{"system": f"{NS}/sid/ph-pseudonym", "value": out["id"]}]
        out["name"] = [{"extension": [{"url": C.DAR_EXT, "valueCode": "masked"}]}]
        out.pop("telecom", None)
        out.pop("photo", None)
        out.pop("contact", None)
        addrs = []
        for a in r.get("address", []):  # LDS keeps town/city, state, ZIP; drop street lines
            addrs.append(
                {
                    k: v
                    for k, v in a.items()
                    if k in ("use", "city", "district", "state", "postalCode", "country")
                }
            )
        out["address"] = addrs
    else:
        subj = r.get("subject", {}).get("reference", "")
        if subj.startswith("Patient/"):
            out["subject"] = {"reference": f"Patient/{pseudonym(subj.split('/', 1)[1])}"}
        for k in ("participant", "requester", "performer", "location", "reasonCode", "dosageInstruction"):
            if t == "MedicationRequest" and k in ("reasonCode", "dosageInstruction"):
                continue
            out.pop(k, None)
        if t == "Condition":
            out.pop("encounter", None)
    return out, "kept"


def treatment_view(r: dict) -> dict:
    """Treatment responses carry the full record (HIPAA minimum necessary does not apply to
    disclosures to a provider for treatment, 45 CFR 164.502(b)(2)(i)); only internal linkage
    tokens are removed."""
    out = copy.deepcopy(r)
    if out.get("resourceType") == "Patient":
        out["extension"] = [e for e in out.get("extension", []) if e.get("url") != LINKAGE_EXT]
        if not out["extension"]:
            out.pop("extension")
    return out

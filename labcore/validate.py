"""FHIR structural validation + lightweight US Core 6.1.0 "must have" checks.

Structural validation uses the `fhir.resources` R4B models (types, cardinality, unknown
elements, primitive formats) plus explicit checks of the R4 *required* value-set bindings
listed in REQUIRED_CODES / REQUIRED_CC (the models do not enforce bindings). Per the official R4->R4B diff
(hl7.org/fhir/R4B/diff.html), Patient, Condition, Encounter, MedicationRequest, Organization,
Bundle and OperationOutcome are unchanged between R4 and R4B; Observation differs only in
allowing extra Observation.subject target types, so we additionally check that every
Observation.subject references a Patient (the R4 rule we rely on).

The US Core checks implement the human-readable "Each <Resource> Must Have" lists from the
US Core 6.1.0 profile pages. This is NOT a substitute for the official HL7 FHIR Validator.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from importlib import import_module

from . import codes as C

_MODELS = {
    "Patient": "patient",
    "Condition": "condition",
    "Observation": "observation",
    "Encounter": "encounter",
    "MedicationRequest": "medicationrequest",
    "Organization": "organization",
    "Bundle": "bundle",
    "OperationOutcome": "operationoutcome",
}


# R4 required bindings for `code`-typed elements used in this project. fhir.resources validates
# structure, types and cardinality but not value-set membership, so we check these explicitly.
REQUIRED_CODES = {
    ("Patient", "gender"): {"male", "female", "other", "unknown"},
    ("Observation", "status"): {
        "registered",
        "preliminary",
        "final",
        "amended",
        "corrected",
        "cancelled",
        "entered-in-error",
        "unknown",
    },
    ("Encounter", "status"): {
        "planned",
        "arrived",
        "triaged",
        "in-progress",
        "onleave",
        "finished",
        "cancelled",
        "entered-in-error",
        "unknown",
    },
    ("MedicationRequest", "status"): {
        "active",
        "on-hold",
        "cancelled",
        "completed",
        "entered-in-error",
        "stopped",
        "draft",
        "unknown",
    },
    ("MedicationRequest", "intent"): {
        "proposal",
        "plan",
        "order",
        "original-order",
        "reflex-order",
        "filler-order",
        "instance-order",
        "option",
    },
}
REQUIRED_CC = {
    ("Condition", "clinicalStatus"): (
        C.COND_CLINICAL,
        {"active", "recurrence", "relapse", "inactive", "remission", "resolved"},
    ),
    ("Condition", "verificationStatus"): (
        C.COND_VER,
        {"unconfirmed", "provisional", "differential", "confirmed", "refuted", "entered-in-error"},
    ),
}


def _binding_errors(r: dict) -> list[str]:
    t = r.get("resourceType")
    errs = [
        f"{t}.{el} '{r[el]}' not in required value set"
        for (rt, el), vs in REQUIRED_CODES.items()
        if rt == t and el in r and r[el] not in vs
    ]
    for (rt, el), (system, vs) in REQUIRED_CC.items():
        if rt == t and el in r:
            for c in r[el].get("coding", []):
                if c.get("system") == system and c.get("code") not in vs:
                    errs.append(f"{t}.{el} '{c.get('code')}' not in required value set")
    return errs


def _model(rtype: str):
    mod = import_module(f"fhir.resources.R4B.{_MODELS[rtype]}")
    return getattr(mod, rtype)


def structural_errors(resource: dict) -> list[str]:
    rtype = resource.get("resourceType")
    if rtype not in _MODELS:
        return [f"unsupported resourceType {rtype!r}"]
    try:
        _model(rtype).model_validate(resource)
    except Exception as exc:  # pydantic.ValidationError
        return [str(exc).splitlines()[0]]
    if rtype == "Observation" and not str(resource.get("subject", {}).get("reference", "")).startswith(
        "Patient/"
    ):
        return ["Observation.subject must reference a Patient (R4)"]
    return _binding_errors(resource)


def _codes(cc: dict | None) -> set[tuple[str, str]]:
    return {(c.get("system"), c.get("code")) for c in (cc or {}).get("coding", [])}


def us_core_errors(r: dict) -> list[str]:
    """Return violations of US Core 6.1.0 mandatory elements for the profile claimed in meta.profile."""
    errs: list[str] = []
    profiles = set(r.get("meta", {}).get("profile", []))
    t = r.get("resourceType")
    if t == "Patient" and C.PROFILE["Patient"] in profiles:
        if not r.get("identifier"):
            errs.append("Patient.identifier missing")
        names = r.get("name") or []
        if not names:
            errs.append("Patient.name missing")
        for n in names:  # us-core-6
            has = n.get("family") or n.get("given")
            dar = any(e.get("url") == C.DAR_EXT for e in n.get("extension", []))
            if not has and not dar:
                errs.append("us-core-6: name needs family/given or data-absent-reason")
        if not r.get("gender"):
            errs.append("Patient.gender missing")
    elif t == "Condition" and C.PROFILE["Condition"] in profiles:
        cats = set().union(*(_codes(c) for c in r.get("category", []))) if r.get("category") else set()
        if not (
            {(C.COND_CATEGORY, "problem-list-item")} & cats or any(c[1] == "health-concern" for c in cats)
        ):
            errs.append("Condition.category must include problem-list-item or health-concern")
        if not r.get("code"):
            errs.append("Condition.code missing")
        if not r.get("subject"):
            errs.append("Condition.subject missing")
    elif t == "Observation" and C.PROFILE["BloodPressure"] in profiles:
        if (C.LOINC, "85354-9") not in _codes(r.get("code")):
            errs.append("BP code must be LOINC 85354-9")
        comp = [_codes(c.get("code")) for c in r.get("component", [])]
        for need in ("8480-6", "8462-4"):
            if not any((C.LOINC, need) in cs for cs in comp):
                errs.append(f"BP component {need} missing")
        for c in r.get("component", []):
            q = c.get("valueQuantity")
            if q is None and not c.get("dataAbsentReason"):
                errs.append("BP component without value needs dataAbsentReason")
            if q is not None and (q.get("system") != C.UCUM or q.get("code") != "mm[Hg]"):
                errs.append("BP component unit must be UCUM mm[Hg]")
    elif t == "Observation" and C.PROFILE["Lab"] in profiles:
        cats = set().union(*(_codes(c) for c in r.get("category", []))) if r.get("category") else set()
        if (C.OBS_CATEGORY, "laboratory") not in cats:
            errs.append("Lab Observation.category must include laboratory")
        if not r.get("code"):
            errs.append("Lab Observation.code missing")
    elif t == "Encounter" and C.PROFILE["Encounter"] in profiles:
        for el in ("status", "class", "type", "subject"):
            if not r.get(el):
                errs.append(f"Encounter.{el} missing")
    elif t == "MedicationRequest" and C.PROFILE["MedicationRequest"] in profiles:
        for el in ("status", "intent", "subject"):
            if not r.get(el):
                errs.append(f"MedicationRequest.{el} missing")
        if not (r.get("medicationCodeableConcept") or r.get("medicationReference")):
            errs.append("MedicationRequest.medication[x] missing")
    return errs

"""Standard code constants used across the project.

Every code below was looked up against an official/authoritative terminology service on
2026-11-05 (see docs/references.md):
  * SNOMED CT  -> tx.fhir.org CodeSystem/$lookup (SNOMED CT International)
  * LOINC      -> NLM Clinical Tables LOINC API (loinc_items)
  * ICD-10-CM  -> NLM Clinical Tables ICD-10-CM API
  * RxNorm     -> NLM RxNav REST API (rxcui/{id}/properties)
  * HL7 terminology (v3-ActCode, v3-ActReason, condition-category, ...) -> terminology.hl7.org / tx.fhir.org
No code in this file is invented. Local codes (systems under labcore.config.NS) are explicitly
synthetic "EHR flavor" codes that must be mapped (see exchange/mappings/local_code_map.csv).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

from .config import NS

# ---- Code system URIs (FHIR canonical) -----------------------------------------------------
SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UCUM = "http://unitsofmeasure.org"
CDC_RACE_ETH = "urn:oid:2.16.840.1.113883.6.238"
V3_ACTCODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
V3_ACTREASON = "http://terminology.hl7.org/CodeSystem/v3-ActReason"
COND_CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category"
COND_CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical"
COND_VER = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason"
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"

US_CORE = "http://hl7.org/fhir/us/core/StructureDefinition"
US_CORE_RACE = f"{US_CORE}/us-core-race"
US_CORE_ETHNICITY = f"{US_CORE}/us-core-ethnicity"
DAR_EXT = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"

# US Core 6.1.0 profile canonicals used in meta.profile
PROFILE = {
    "Patient": f"{US_CORE}/us-core-patient",
    "Condition": f"{US_CORE}/us-core-condition-problems-health-concerns",
    "BloodPressure": f"{US_CORE}/us-core-blood-pressure",
    "Lab": f"{US_CORE}/us-core-observation-lab",
    "Encounter": f"{US_CORE}/us-core-encounter",
    "MedicationRequest": f"{US_CORE}/us-core-medicationrequest",
    "Organization": f"{US_CORE}/us-core-organization",
}

# ---- Synthetic-data labels applied to every FHIR resource ---------------------------------
SYNTHETIC_TAG = {
    "system": f"{NS}/CodeSystem/data-provenance",
    "code": "synthetic",
    "display": "Synthetic data — for demonstration only.",
}
# HL7 v3 ActReason HTEST = "test health data"
HTEST_SECURITY = {"system": V3_ACTREASON, "code": "HTEST", "display": "test health data"}

# ---- Conditions -----------------------------------------------------------------------------
HTN_SNOMED = (SNOMED, "59621000", "Essential hypertension")
HTN_ICD = (ICD10CM, "I10", "Essential (primary) hypertension")
T2DM_SNOMED = (SNOMED, "44054006", "Type 2 diabetes mellitus")
T1DM_SNOMED = (SNOMED, "46635009", "Type 1 diabetes mellitus")
T2DM_ICD = (ICD10CM, "E11.9", "Type 2 diabetes mellitus without complications")
T2DM_HYPER_ICD = (ICD10CM, "E11.65", "Type 2 diabetes mellitus with hyperglycemia")
T1DM_ICD = (ICD10CM, "E10.9", "Type 1 diabetes mellitus without complications")
ESRD_SNOMED = (SNOMED, "46177005", "End-stage renal disease")
ESRD_ICD = (ICD10CM, "N18.6", "End stage renal disease")

# Unrelated / sensitive conditions (present in source EHRs; NOT minimum-necessary for this use case)
OTHER_CONDITIONS = [
    ((SNOMED, "10509002", "Acute bronchitis"), (ICD10CM, "J20.9", "Acute bronchitis, unspecified")),
    ((SNOMED, "195662009", "Acute viral pharyngitis"), (ICD10CM, "J02.9", "Acute pharyngitis, unspecified")),
    ((SNOMED, "444814009", "Viral sinusitis"), (ICD10CM, "J01.90", "Acute sinusitis, unspecified")),
    (
        (SNOMED, "370143000", "Major depressive disorder"),
        (ICD10CM, "F32.9", "Major depressive disorder, single episode, unspecified"),
    ),
]

# ---- Observations ---------------------------------------------------------------------------
BP_PANEL = (LOINC, "85354-9", "Blood pressure panel with all children optional")
SYSTOLIC = (LOINC, "8480-6", "Systolic blood pressure")
DIASTOLIC = (LOINC, "8462-4", "Diastolic blood pressure")
HBA1C = (LOINC, "4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood")
HBA1C_HPLC = (LOINC, "17856-6", "Hemoglobin A1c/Hemoglobin.total in Blood by HPLC")
BODY_WEIGHT = (LOINC, "29463-7", "Body weight")
BMI = (LOINC, "39156-5", "Body mass index (BMI) [Ratio]")

# ---- Encounters -----------------------------------------------------------------------------
ENC_CHECKUP = (SNOMED, "185349003", "Encounter for check up")
ENC_FOLLOWUP = (SNOMED, "390906007", "Follow-up encounter")
ENC_ED = (SNOMED, "50849002", "Emergency room admission")
CLASS_AMB = (V3_ACTCODE, "AMB", "ambulatory")
CLASS_EMER = (V3_ACTCODE, "EMER", "emergency")
CLASS_IMP = (V3_ACTCODE, "IMP", "inpatient encounter")

# ---- Medications (RxNorm SCD) ---------------------------------------------------------------
MEDS_HTN = [
    ("314076", "lisinopril 10 MG Oral Tablet"),
    ("197361", "amlodipine 5 MG Oral Tablet"),
    ("310798", "hydrochlorothiazide 25 MG Oral Tablet"),
    ("979492", "losartan potassium 50 MG Oral Tablet"),
]
MEDS_DM = [
    ("861007", "metformin hydrochloride 500 MG Oral Tablet"),
    ("310490", "glipizide 5 MG Oral Tablet"),
]

# Free-text medication strings emitted by an EHR that does not code medications (must be mapped)
MED_FREE_TEXT = {
    "314076": "Lisinopril 10mg tablet",
    "197361": "Amlodipine 5mg tab",
    "310798": "HCTZ 25 mg tablet",
    "979492": "Losartan 50mg tab",
    "861007": "Metformin 500mg tablet",
    "310490": "Glipizide 5 mg tab",
}

# ---- Race / ethnicity (CDC Race & Ethnicity code system, OMB categories) ----------------------
RACE = {
    "2106-3": "White",
    "2054-5": "Black or African American",
    "2028-9": "Asian",
    "1002-5": "American Indian or Alaska Native",
    "2076-8": "Native Hawaiian or Other Pacific Islander",
}
ETHNICITY = {"2135-2": "Hispanic or Latino", "2186-5": "Not Hispanic or Latino"}

# ---- Local ("EHR flavor") code systems -- synthetic, must be mapped ---------------------------
LOCAL_DX_RHC = f"{NS}/CodeSystem/prairie-rhc-local-dx"
LOCAL_LAB_FQHC = f"{NS}/CodeSystem/harbor-chc-local-lab"
LOCAL_DX_CODES = {"HTN": HTN_SNOMED, "DM2": T2DM_SNOMED, "ESRD": ESRD_SNOMED}

# IFCC -> NGSP master equation (NGSP %, IFCC mmol/mol), published by NGSP (ngsp.org/ifccngsp.asp)
IFCC_SLOPE = 0.09148
IFCC_INTERCEPT = 2.152


def ifcc_to_ngsp(mmol_per_mol: float) -> float:
    return round(IFCC_SLOPE * mmol_per_mol + IFCC_INTERCEPT, 1)


def ngsp_to_ifcc(percent: float) -> float:
    return round((percent - IFCC_INTERCEPT) / IFCC_SLOPE)


def coding(t: tuple[str, str, str]) -> dict:
    system, code, display = t
    return {"system": system, "code": code, "display": display}

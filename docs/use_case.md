# Use case: Chronic disease surveillance through network exchange

> Synthetic data — for demonstration only. Independent portfolio project. Not affiliated with, endorsed by, or produced for CDC, ONC/ASTP, The Sequoia Project, or any QHIN. Not a TEFCA implementation. All data are synthetic.

*This page is a reusable template.* Bracketed guidance like **[adapt: …]** marks the places a real program would fill in its own jurisdiction, partners and measures. Sources are listed in [references.md](references.md).

| Field | Value |
|---|---|
| Use case ID | CDX-UC-01 |
| Title | Population-level hypertension and diabetes surveillance through standardized network exchange |
| Exchange purpose | Public Health, modeled on TEFCA XP code `T-PH` ([T3], [T4]); `T-TREAT` is used only for the contrast flow |
| Version / status | 0.1 / demonstration on synthetic data |
| Standards baseline | FHIR R4 (4.0.1); US Core 6.1.0; USCDI v3; Bulk Data Access 2.0.0 ([S1]–[S4]) |
| Measurement period | Calendar year 2025 (the 2025 eCQM performance period) |

## 1. Problem and goal

Today, chronic disease surveillance in a jurisdiction usually depends on surveys, claims, or a patchwork of one-off EHR extracts. Each extract has its own reporting interface, file layout and data use agreement, so providers repeat the work for every request and the health department receives inconsistent data. Patients seen at more than one organization are counted twice, and local codes disappear from analyses without anyone noticing.

**Goal:** a public health authority (PHA) uses one standardized, purpose-checked network request to obtain a minimum-necessary, US Core-aligned dataset from many organizations. It then produces population measures for hypertension (HTN) and diabetes (DM) by organization, age, sex, county and rurality, and uses them for surveillance and program action (for example, targeting BP-control outreach to counties that are falling behind).

## 2. Actors

| Actor | Role in the flow | Simulated as |
|---|---|---|
| **PHA epidemiologist / analyst** (primary) | Defines the request, receives data, runs normalization, linkage and measures | `lkdph`, Lakeland Department of Public Health (fictional) |
| **PHA data steward / privacy officer** | Approves the minimum-necessary profile and data use terms; owns PPRL key management | Policy configuration in `network/policy.py` |
| **Responding healthcare organizations** (5) | Hold source EHR data; expose FHIR APIs; compute linkage tokens | `amc`, `rhc`, `fqhc`, `ipp`, `mmg` nodes |
| **Network intermediary** | Authenticates, checks purpose and role, routes, filters, audits | `network/broker.py` (a stand-in for QHIN-level services) |
| **Clinician** (contrast flow) | Requests one patient's record for treatment | `amc-clinician` |
| **Non-authorized requester** (negative tests) | Asserts a purpose it is not entitled to | `acme-health-plan` |
| **Community / patients** | Data subjects; benefit from program action | Synthetic persons (ground truth kept separately) |

## 3. Preconditions

1. The PHA, the network and the responding organizations have agreements in place, and the PHA's identity, role (PHA) and jurisdiction are registered in the network directory. **[adapt: Common Agreement / Terms of Participation, state law, DUA]**
2. A minimum-necessary **data profile** (`ph-chronic-disease-lds-v1`) has been agreed. It covers resource types, value sets, a limited-data-set transformation and date-range rules.
3. Responders expose FHIR R4 / US Core-conformant search and Bulk Data `$export`, and **register any local codes** they use for in-scope concepts so filtering doesn't drop them.
4. A PPRL standardization method and key are agreed. (The demo key is public; see [limitations](limitations.md).)
5. The PHA maintains a terminology crosswalk (`exchange/mappings/local_code_map.csv`) and its measure specifications.

## 4. Triggers

- A scheduled surveillance cycle (for example, monthly or quarterly), or
- An ad-hoc program need, such as evaluating a BP-control initiative or responding to a legislative request.

## 5. Main flow (Flow A, `T-PH`)

| Step | Actor | Action | Standard / artifact |
|---|---|---|---|
| A1 | PHA | Builds a request envelope: purpose `T-PH`, jurisdiction, date range, resource types, targets `*` | [data_sharing_protocol.md §2](data_sharing_protocol.md) |
| A2 | Broker | Authenticates the requester; checks the XP code, role=PHA, jurisdiction match, presence of a date range and allowed types; writes audit entries | XP SOP [T3]; PH SOP [T4] |
| A3 | Broker → nodes | Kick-off: `GET /Patient/$export?_type=…` with `Prefer: respond-async` | Bulk Data 2.0.0 [S3] |
| A4 | Node | `202 Accepted` + `Content-Location`; status `202` (X-Progress) then `200` with a manifest; NDJSON files. Patient records carry source-computed PPRL tokens | [S3] |
| A5 | Broker | Applies the minimum-necessary filter: limited data set (no names, MRNs, telecom or street), value-set and date-range filtering, pseudonymous IDs; logs counts kept and withheld per reason | 45 CFR 164.514(e) [L2] |
| A6 | PHA | Polls the broker's status, downloads per-node NDJSON, then sends `DELETE` (the broker purges its outbox) | [S3]; PH SOP §5.4 [T4] |
| A7 | PHA | **Normalizes** to analysis tables aligned with US Core / USCDI v3: pairs split BP observations, falls back to `issued` when `effective` is missing, derives county from ZIP | `exchange/normalize.py` |
| A8 | PHA | **Maps** local codes to SNOMED CT / LOINC / RxNorm, converts IFCC mmol/mol to NGSP %, normalizes unit strings | `local_code_map.csv` |
| A9 | PHA | **Deduplicates** across organizations by linking on PPRL tokens and closing links transitively | `exchange/linkage.py` |
| A10 | PHA | Computes measures and data quality; reviews small cells; publishes aggregate results | `measures/` |

### Alternate and exception flows

| ID | Condition | Handling |
|---|---|---|
| X1 | Requester isn't a PHA (e.g., a health plan asserts `T-PH`) | `403` OperationOutcome; audited as `denied` |
| X2 | Missing date range or jurisdiction | `400` (the PH SOP requires both) |
| X3 | `T-PH-ECR` / `T-PH-ELR` used for a query | `400`: these XP codes are push/message-delivery only [T3] |
| X4 | Resource types beyond the profile | `403`: exceeds minimum necessary |
| X5 | Unsupported purpose (e.g., `T-PYMNT`) or unknown code | `403` / `400` |
| X6 | A node is unreachable or returns an error | Logged per node; the PHA receives partial results and the manifest shows which nodes contributed **[adapt: completeness thresholds before publishing]** |
| X7 | Late data (batch loading) | Records with `lastUpdated` after the extract date aren't visible; reported as "pending" in data quality |
| X8 | Uncertain linkage | Linked conservatively (precision first); residual duplicates are reported via evaluation |
| B | **Contrast flow, `T-TREAT`**: a clinician queries one patient by demographics | Full record including identifiers, from every node with a match; no minimum-necessary filter (45 CFR 164.502(b)(2)(i)) |

## 6. Postconditions

- The PHA holds pseudonymous, linked, standardized analysis tables plus aggregate measures.
- The broker holds **no** retained clinical payload, only the audit log.
- Every request, decision, node interaction and delivery is in the hash-chained audit log.

## 7. Data elements

Minimum-necessary column: ✅ sent under `T-PH`, ✳️ transformed, ❌ withheld.

| Data element | USCDI v3 class → element | FHIR resource / US Core 6.1.0 profile → element | Code system / value set | T-PH |
|---|---|---|---|---|
| Patient identifier | Patient Demographics (identifier is required by US Core) | Patient / us-core-patient → `identifier` | Source MRN → replaced by pseudonym | ✳️ |
| First / last name | Patient Demographics → First Name, Last Name | Patient → `name` | — | ❌ (masked with data-absent-reason, which satisfies us-core-6) |
| Date of birth | Patient Demographics → Date of Birth | Patient → `birthDate` | — | ✅ (dates are allowed in a limited data set) |
| Sex | Patient Demographics → Sex | Patient → `gender` (administrative gender) | FHIR AdministrativeGender | ✅ |
| Race | Patient Demographics → Race | Patient → `extension:us-core-race` (`ombCategory`) | CDC Race & Ethnicity (`urn:oid:2.16.840.1.113883.6.238`), OMB categories | ✅ |
| Ethnicity | Patient Demographics → Ethnicity | Patient → `extension:us-core-ethnicity` | CDC Race & Ethnicity, OMB categories | ✅ |
| Current address | Patient Demographics → Current Address | Patient → `address` | — | ✳️ city, `district` (county), state, ZIP only |
| Phone | Patient Demographics → Phone Number | Patient → `telecom` | — | ❌ |
| Linkage tokens | (not a USCDI element) | Patient → project extension `pprl-linkage-tokens` | HMAC-SHA256 tokens | ✅ |
| Problems (HTN, DM, ESRD) | Problems → Problems; Date of Diagnosis | Condition / us-core-condition-problems-health-concerns → `code`, `onsetDateTime`, `recordedDate`, `clinicalStatus` | SNOMED CT 59621000, 44054006, 46635009, 46177005; ICD-10-CM I10, E11.9, E11.65, E10.9, N18.6; registered local codes | ✅ in value set |
| Other problems | Problems → Problems | Condition | e.g., SNOMED 370143000 | ❌ (not minimum necessary; can be sensitive) |
| Systolic / diastolic BP | Vital Signs → Systolic, Diastolic Blood Pressure | Observation / us-core-blood-pressure → `component` 8480-6, 8462-4 (panel 85354-9) | LOINC; UCUM `mm[Hg]` | ✅ |
| HbA1c | Laboratory → Tests; Values/Results | Observation / us-core-observation-lab → `code`, `valueQuantity` | LOINC 4548-4, 17856-6 (registered local IFCC code mapped to 4548-4); UCUM `%` | ✅ |
| Other vitals (e.g., weight) | Vital Signs → Body Weight | Observation | LOINC 29463-7 | ❌ |
| Medications | Medications → Medications | MedicationRequest / us-core-medicationrequest → `medicationCodeableConcept`, `authoredOn` | RxNorm SCDs (antihypertensives, antidiabetics) | ✅ |
| Encounter type / time / class | Encounter Information → Encounter Type, Encounter Time | Encounter / us-core-encounter → `type`, `period`, `class`, `serviceProvider` | SNOMED CT (185349003, 390906007, 50849002); v3-ActCode AMB/EMER/IMP | ✅ (participants removed) |

## 8. Measure specifications

| Measure | Based on | Population and logic implemented | Simplifications (vs the source eCQM) |
|---|---|---|---|
| **HTN prevalence** | Surveillance indicator (not an eCQM) | Adults 18+ with a qualifying ambulatory visit in the MP; numerator = active HTN dx with onset ≤ MP end | Clinic-based (not population-representative); diagnosis-based (undiagnosed HTN is missed, which the ground-truth comparison makes visible) |
| **DM prevalence** | Surveillance indicator | Same denominator; active type 1 or 2 diabetes | Same as above |
| **Controlling high BP** | CMS165v13 [M1] | Age 18-85 at MP end; qualifying visit; essential HTN onset ≤ 2025-06-30; exclude ESRD; numerator = most recent non-ED, non-inpatient BP date in the MP with lowest systolic < 140 **and** lowest diastolic < 90; no BP → not controlled | Small code subsets, not the full VSAC value sets. Any ambulatory encounter counts as a qualifying visit. Exclusions implemented: **ESRD only**; pregnancy, hospice, palliative care, frailty/advanced illness and nursing-home exclusions are **not** implemented (the generator doesn't model them). Device and remote-monitoring source rules are not modeled. Missing `clinicalStatus` is treated as active. |
| **Glycemic status > 9% (inverse)** | CMS122v13 [M3] | Age 18-75; diabetes with onset ≤ MP end; qualifying visit; numerator = most recent HbA1c in the MP (lowest that day) > 9.0%, or none | HbA1c only (GMI not modeled). Exclusions not implemented (same reason). Observations missing `effectiveDateTime` use `issued`. |

Stratifiers: attributed organization (most MP visits), age group (18-44, 45-64, 65+), administrative sex, county, rurality. Cells with numerator < 11 or denominator < 30 are flagged as `small_cell` **[adapt: jurisdictional suppression rules]**.

## 9. Success criteria

| Criterion | Target | Result on synthetic data (`make pipeline`) |
|---|---|---|
| All refusal scenarios return the correct status and are audited | 100% | 10/10; every request has `received` + `decision` entries |
| No direct identifiers in Public Health payloads | 0 | Enforced by tests (`tests/test_policy_filtering.py`) |
| FHIR structural validity of exchanged resources | 100% | 100% |
| Dedup precision / recall vs ground truth | ≥ 0.98 / ≥ 0.85 | **0.999 / 0.951** |
| Local-code capture after mapping | 100% of registered local codes | 279 local problem codes, 403 IFCC results, 252 free-text medications, 3,877 non-UCUM BP units mapped |
| Network adds information beyond a single organization | Measurable | 19-27% of each organization's adult patients have records elsewhere; 11-19% of BP-control denominators get their most recent BP from another organization |
| Audit integrity | Chain verifies; tampering detected | Verified; tamper tests pass |

## 10. Open questions to validate with real stakeholders

1. Is a population-level `$export` acceptable to responders under `T-PH`, or would a PHA-hosted FHIR query per cohort be preferred? (The PH SOP permits FHIR Query by PHAs; Bulk Data isn't specified.)
2. Who operates PPRL (each source, a trusted third party, or the PHA), and what governance applies to the hashed tokens?
3. What completeness and timeliness thresholds must each node meet before results are published?
4. How should local-code registration be maintained, and by whom?
5. Which sensitive conditions must be excluded under state law, beyond this minimum-necessary profile?

[T3]: references.md
[T4]: references.md
[S1]: references.md
[S3]: references.md
[S4]: references.md
[M1]: references.md
[M3]: references.md
[L2]: references.md

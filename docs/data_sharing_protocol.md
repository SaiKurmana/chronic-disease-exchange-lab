# Data sharing protocol: chronic disease surveillance via network exchange

> Synthetic data — for demonstration only. Independent portfolio project. Not affiliated with, endorsed by, or produced for CDC, ONC/ASTP, The Sequoia Project, or any QHIN. Not a TEFCA implementation. All data are synthetic. This material is descriptive and educational; it is not legal advice.

*Reusable template.* Protocol ID **`cdx-protocol`**, version **0.1.0**; data profile **`ph-chronic-disease-lds-v1`**. Sources are in [references.md](references.md).

## 1. Scope

This protocol defines how a public health authority (PHA) requests chronic disease data (hypertension, diabetes, ESRD exclusion, BP, HbA1c, related medications and encounters) from participating organizations through a network intermediary, under a declared **Public Health** exchange purpose. It also defines a contrasting **Treatment** patient query. Real TEFCA exchange is governed by the Common Agreement, the SOPs and the QHIN Technical Framework; this protocol is a simplified illustration (see [architecture.md](architecture.md)).

## 2. Request specification

### 2.1 Envelope (requester → broker)

`POST /exchange/$export` (population) or `POST /exchange/patient-query` (patient-level), `Content-Type: application/json`:

```json
{
  "request_id": "req-0001-ph-bulk",
  "requester": {"id": "lkdph", "credential": "<network-issued credential>"},
  "purpose": "T-PH",
  "operation": "bulk-export",
  "jurisdiction": "Lakeland State",
  "date_range": {"start": "2024-01-01", "end": "2025-12-31"},
  "resource_types": ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest"],
  "targets": ["*"]
}
```

| Field | Required | Rules |
|---|---|---|
| `request_id` | yes | Unique per request; carried to every node and audit row (`X-Request-Id`) |
| `requester.id` / credential | yes | Must match a directory entry; role is taken from the directory, not from the request |
| `purpose` | yes | A TEFCA XP code ([T3]); the network only accepts the codes it supports (§3) |
| `operation` | yes | `bulk-export` (T-PH) or `patient-query` (T-TREAT) |
| `jurisdiction` | T-PH | Must equal the PHA's registered jurisdiction (modeled on the PH SOP `tefca_phj` requirement [T4]) |
| `date_range` | T-PH | Required (PH SOP [T4]); ISO dates; `start ≤ end` |
| `resource_types` | optional | Must be a subset of the data profile |
| `patient` | patient-query | `family`, `given`, `birthdate` |
| `targets` | optional | Node IDs or `*` |

### 2.2 Broker → node (FHIR)

- `GET [node]/Patient/$export?_type=…&_outputFormat=application/fhir+ndjson` with `Prefer: respond-async` ([S3])
- Headers: `Authorization: Bearer <network token>`, `X-Request-Id`, `X-Exchange-Purpose`, `X-Requester-Id`
- Patient-level: `GET [node]/Patient?family=&given=&birthdate=`, then `GET [node]/{type}?patient={id}`

## 3. Exchange purpose handling

| XP code ([T3]) | Allowed requester role | Allowed operation | Response content |
|---|---|---|---|
| `T-PH` Public Health | PHA (or delegate) | `bulk-export` | Limited data set filtered to the data profile (§4) |
| `T-TREAT` Treatment | Health Care Provider | `patient-query` | Full record for matched patient(s) |
| `T-PH-ECR`, `T-PH-ELR` | — | none | `400`: push/message delivery only, no queries ([T3]) |
| `T-PYMNT`, `T-HCO*`, `T-IAS`, `T-GOVDTRM*`, `T-TRTMNT` | — | none in this network | `403`: recognized but not supported by these responders |
| anything else | — | — | `400`: unknown code |

The broker denies by default. A request is permitted only if every check passes, and the decision is audited before any routing happens.

## 4. Minimum necessary (data profile `ph-chronic-disease-lds-v1`)

Designed around the limited data set definition (45 CFR 164.514(e)(2)) and HIPAA minimum necessary ([L2], [L3]):

| Resource | Kept | Removed or transformed |
|---|---|---|
| Patient | `birthDate`, `gender`, race/ethnicity extensions, address `city`/`district`/`state`/`postalCode`, PPRL tokens | `name` → data-absent-reason `masked`; `identifier` → requester-specific pseudonym; `telecom`, `address.line`, `photo`, `contact` removed |
| Condition | Codes in the HTN/DM/ESRD value sets (+ registered local codes); onset ≤ end of range | Other conditions (including sensitive ones) withheld; `encounter` link removed |
| Observation | BP (85354-9 / 8480-6 / 8462-4) and HbA1c (4548-4, 17856-6, registered local) inside the date range | All other observations withheld; `performer` and `note` removed |
| MedicationRequest | RxNorm antihypertensive and antidiabetic SCDs (+ registered free text) inside the date range | Other medications withheld; `requester` removed |
| Encounter | `class`, `type`, `period`, `serviceProvider` inside the date range | `participant`, `location`, `reasonCode` removed |

Every withheld record is counted by reason in the audit `detail` field.

## 5. Response specification

- **Broker kick-off:** `202 Accepted`, `Content-Location: {broker}/exchange/status/{job}`
- **Status:** `200` with a Bulk Data manifest: `transactionTime`, `request`, `requiresAccessToken: true`, `output[{type, url, count}]` (one file per node and type), `error[]`. Manifest-level `extension` carries `purpose`, `filter_profile` and per-node returned/withheld counts.
- **Files:** `application/fhir+ndjson`, sorted by resource id.
- **Cleanup:** `DELETE` on the status URL → `202`; after that the status URL returns `404`.
- **Patient query:** `200` with a FHIR `Bundle` (type `collection`) whose `fullUrl`s name the source node; the per-node summary is returned in the `X-Node-Summary` header.

## 6. Consent considerations

- HIPAA permits public health disclosures to a PHA without individual authorization (45 CFR 164.512(b) [L1]). Other law may still require consent or restrict sharing (for example, state laws on sensitive conditions, or 42 CFR Part 2 for substance use disorder records). **[adapt]**
- This profile reduces the problem by excluding non-target conditions. Production systems need data segmentation (security labels) and consent-policy evaluation at the source.
- Patient-facing transparency (notices, a public description of uses) is recommended even where consent isn't required.
- Treatment queries rely on the provider's treatment relationship; consent policies for sensitive data still apply at the source.

## 7. Security (described generically)

| Control | Pattern (real world) | In this simulation |
|---|---|---|
| Organization identity and trust | Network-issued certificates; mutual TLS; dynamic client registration (e.g., HL7 FAST UDAP, referenced by the Facilitated FHIR SOP [T5]) | Directory entry + demo credential |
| Authorization | OAuth 2.0 client-credentials with signed JWT assertions (SMART Backend Services) and scoped access tokens | HMAC "network token" bound to `request_id`; nodes reject requests without it (`401`) |
| Transport | TLS 1.2+ everywhere | In-process calls (no network) |
| Least privilege | Role- and purpose-scoped tokens; per-type scopes | Role/purpose/operation matrix (§3); data profile (§4) |
| Data at rest | Encrypted storage; short retention for staging data | Broker outbox purged on `DELETE`; PHA tables are local files |
| Key management | HSM / KMS, rotation, separation of duties for the PPRL key | Demo keys are public constants (**never** do this in production) |

## 8. Audit

Every request produces an ordered set of append-only entries: `request.received`, `request.decision`, then per node `node.export` / `node.query` and `broker.min_necessary_filter`, then `response.*`. Each row records **who** (requester id and role), **why** (XP code), **what** (operation, resource types, date range, jurisdiction, records returned and withheld), **when** (timestamp from a deterministic logical clock in the demo), the **outcome** (status), and the `prev_hash`/`entry_hash` that form a SHA-256 chain. Any edit, deletion or reordering breaks verification (`network/audit.py`, `tests/test_bulk_and_audit.py`).

## 9. Error handling

All errors are FHIR `OperationOutcome` resources with `severity`, an `issue.code` from the FHIR IssueType value set, and `diagnostics`.

| Situation | HTTP | `issue.code` |
|---|---|---|
| Unknown requester or bad credential | 401 | `login` |
| Role/purpose/operation not permitted; jurisdiction mismatch; types exceed profile | 403 | `forbidden` / `not-supported` |
| Missing date range or jurisdiction; unknown XP; push-only XP queried | 400 | `required` / `code-invalid` / `not-supported` |
| Unknown or deleted job | 404 | `not-found` |
| Node error during fan-out | logged per node; partial result | `error` in the audit `detail` field |

Clients should back off exponentially when polling and honor `Retry-After` ([S3]).

## 10. Versioning and change management

- The protocol uses semantic versioning (`MAJOR.MINOR.PATCH`). A MAJOR version changes the envelope or response semantics; MINOR adds optional fields or new data elements to the profile; PATCH covers clarifications.
- The data profile ID (`ph-chronic-disease-lds-v1`) is versioned separately and stamped into every manifest and audit row, so analyses can be reproduced.
- The standards baseline is pinned (FHIR 4.0.1, US Core 6.1.0, USCDI v3, Bulk Data 2.0.0). Upgrades follow the regulatory and SOP baselines with a published deprecation window. **[adapt: e.g., 6-12 months]**
- Value sets and crosswalks are versioned files under change control.

[T3]: references.md
[T4]: references.md
[T5]: references.md
[S3]: references.md
[L1]: references.md
[L2]: references.md
[L3]: references.md

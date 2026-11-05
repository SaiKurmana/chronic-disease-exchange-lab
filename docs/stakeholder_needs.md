# Stakeholder needs and expectations: a framework to validate

> Synthetic data — for demonstration only. Independent portfolio project. Not affiliated with, endorsed by, or produced for CDC, ONC/ASTP, The Sequoia Project, or any QHIN. Not a TEFCA implementation. All data are synthetic.

**This is a generic framework, not research findings.** No real stakeholders were interviewed. Each statement is a *hypothesis* to test in discovery interviews, workshops or advisory groups. Use the columns as a checklist: confirm, revise or reject each item, and record the evidence.

## How to use this template

1. For each stakeholder group, schedule 3-5 interviews that cover different organization sizes and settings (urban/rural, large/small).
2. Score each need: **importance** (1-5) and **current pain** (1-5). Items that score high on both are design drivers.
3. Record the evidence (quote, document, metric) and the decision it drives in the "Validated?" column.
4. Re-check against [use_case.md](use_case.md) success criteria and [data_sharing_protocol.md](data_sharing_protocol.md).

## Health departments (state, tribal, local and territorial PHAs)

| Need / expectation (hypothesis) | Why it matters | How this demo addresses it | Validated? |
|---|---|---|---|
| One standardized request instead of many bespoke extracts and portals | Lowers burden for both PHAs and providers | A single envelope and Bulk Data-style flow across all nodes | ☐ |
| Population-level, timely, linkable data at the person level (not visit level) | Avoids double counting; supports incidence and prevalence | PPRL linkage; deduplication shrinks 4,990 apparent persons to 4,465 | ☐ |
| Clear legal basis and a defensible minimum-necessary scope | Public trust; legal review | Purpose and role checks; limited data set profile; audit | ☐ |
| Data-quality transparency by source | Decide what is fit for use | Per-node completeness, validity, conformance and timeliness | ☐ |
| Stratification by geography, age, sex and race/ethnicity for equity analysis | Target programs | County and rurality strata; race/ethnicity completeness tracked | ☐ |
| Sustainable workforce and infrastructure (informatics skills, cloud, terminology services) | Many agencies have limited capacity | Small, open-source, reproducible pipeline | ☐ |

## Healthcare providers (clinics, FQHCs, rural health clinics, independent practices)

| Need / expectation (hypothesis) | Why it matters | How this demo addresses it | Validated? |
|---|---|---|---|
| Minimal added workload; reuse of certified EHR APIs | Small practices lack IT staff | Standard FHIR/US Core and Bulk export; no custom files | ☐ |
| Confidence that disclosures are lawful and limited | Liability, patient trust | XP/role checks; minimum necessary; audit trail | ☐ |
| Recognition of local coding realities | Local codes are common in small EHRs | Sources register local codes; the PHA maps them | ☐ |
| Value back: their own measures compared with network results | Motivation to participate | Single-organization vs network comparison per organization | ☐ |
| Treatment-time access to outside records | Care coordination | Contrast flow under `T-TREAT` | ☐ |

## Health systems (academic medical centers, multi-site groups)

| Need / expectation (hypothesis) | Why it matters | How this demo addresses it | Validated? |
|---|---|---|---|
| Predictable, scalable requests (rate limits, async jobs) | Production load | Asynchronous kick-off and polling pattern | ☐ |
| Clear exchange-purpose semantics and response obligations | Avoid over- or under-sharing | Uses the XP SOP's response obligations ("SHOULD respond" for T-PH) | ☐ |
| Security alignment with network trust frameworks | Security review | Described generically (UDAP/SMART-style, mTLS); simulated tokens | ☐ |
| Reuse of the same pipes for quality reporting and research | Return on investment | Shows how purposes differ in what is returned | ☐ |

## HIEs, networks and intermediaries

| Need / expectation (hypothesis) | Why it matters | How this demo addresses it | Validated? |
|---|---|---|---|
| Directory and routing of public health requests at scale | Network-of-networks reach | Directory plus broker routing (simplified) | ☐ |
| Not persisting payloads they don't need (the PH SOP restricts this) | Compliance | Broker outbox is purged on `DELETE`; only the audit log remains | ☐ |
| Value-added services: linkage, terminology, data quality | Sustainability | PPRL, mapping and DQ shown as separable services | ☐ |
| Consistent audit and accounting of disclosures | Oversight | Hash-chained audit with who / purpose / what / when / outcome | ☐ |

## Patients and communities

| Need / expectation (hypothesis) | Why it matters | How this demo addresses it | Validated? |
|---|---|---|---|
| Privacy: no more identifiable data than necessary | Trust | Limited data set; no names, phone numbers, street addresses or MRNs | ☐ |
| Transparency about how data are used and protected | Trust; legitimacy | Plain-language protocol and audit concept | ☐ |
| Benefit: programs that reduce uncontrolled BP and diabetes complications in their community | Equity | County/rurality strata point to where outreach is needed | ☐ |
| Community voice in which measures and strata are reported | Avoid stigma; actionable data | Small-cell flags; framework item to co-design | ☐ |

## EHR vendors and health IT developers

| Need / expectation (hypothesis) | Why it matters | How this demo addresses it | Validated? |
|---|---|---|---|
| Requirements that use existing standards (US Core, Bulk Data, SMART/UDAP) | Avoid custom builds | Only standard FHIR patterns plus one documented extension | ☐ |
| Clear conformance expectations and test data | Development and testing | US Core "must have" checks; synthetic examples | ☐ |
| Guidance on mapping local codes and units | Reduce support load | Crosswalk and transform examples | ☐ |
| Stable versioning and change notice | Release planning | Versioned protocol and profile IDs (see protocol §9) | ☐ |

## Cross-cutting tensions to explore

- **Linkability vs privacy.** Hashed tokens enable deduplication but are still derived from identifiers.
- **Timeliness vs burden.** More frequent extracts mean more load on small sources.
- **Standardization vs local reality.** The PHA absorbs mapping work; should sources standardize instead?
- **Voluntary response vs completeness.** T-PH is a "SHOULD respond" purpose, so coverage may be uneven.

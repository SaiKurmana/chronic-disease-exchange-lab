# Limitations

> Synthetic data — for demonstration only. Independent portfolio project. Not affiliated with, endorsed by, or produced for CDC, ONC/ASTP, The Sequoia Project, or any QHIN. Not a TEFCA implementation. All data are synthetic.

## Data

- **Synthetic, not Synthea.** Synthea was the preferred generator and was evaluated (Java 21, official jar). A 200-patient run took 69 s and wrote 578 MB of FHIR, so 5,000 patients would mean about 14 GB per run, which doesn't fit a repository under 20 MB or fast deterministic CI ([G1] in [references](references.md)). The project instead uses a seeded Python generator that writes FHIR R4 directly and injects controlled EHR "flavors" with known ground truth. Its clinical realism is **much lower than Synthea's**: there are no disease-progression modules, only five condition families, simplified BP and HbA1c distributions, and invented organization-level effects.
- Prevalence and control rates are **tuned to look plausible**. They are not calibrated to any real population and must not be quoted as estimates for any place.
- The geography is fictional (the "State of Lakeland", ZIP-like codes `000xx`). Rurality is a two-level label, not RUCA/RUCC codes.
- Race and ethnicity are assigned from simple distributions purely to exercise completeness metrics. No inference about real disparities should be drawn.

## Standards conformance

- Structural validation uses `fhir.resources` **R4B** models, which differ from R4 only in extra `Observation.subject` targets for the resources used here (an explicit R4 check is added). Required value-set bindings for the codes we use are checked by hand. **The official HL7 FHIR Validator and US Core profile validation were not run**; the US Core checks only cover the "Must Have" lists.
- Value sets are **small subsets** of the codes the eCQMs use (VSAC value sets require a UMLS license and weren't reproduced). The local codes and the PPRL-token extension URL are project-local and synthetic.
- Bulk Data follows the v2.0.0 patterns but is simplified: the job completes on the second poll, `_since` is supported, and `_typeFilter`, `_elements`, `includeAssociatedData`, Group export and `Expires` headers are not implemented. The broker's combined manifest is a project convention.
- US Core 6.1.0 / USCDI v3 were chosen as the baseline (see [references](references.md) S1, S4). Newer versions (US Core 9.0.0; USCDI v3.1-v6) are not modeled. The USCDI v3 "Sex" element is approximated with administrative gender.

## Measures

- CBP and glycemic-status measures are **adapted** from CMS165v13 and CMS122v13. Most denominator exclusions (pregnancy, hospice, palliative care, frailty/advanced illness, nursing home) are not implemented, GMI isn't modeled, any ambulatory encounter counts as a qualifying visit, and a missing `clinicalStatus` is treated as active. Results are **not** comparable to reported eCQM performance.
- Prevalence is clinic-based (persons with a qualifying visit) and diagnosis-based, so it undercounts true prevalence. The comparison with latent ground truth shows by how much.
- Attribution to a single "organization" uses the organization with the most visits in the measurement period.

## Network and security

- The broker is a single in-process component that stands in for QHINs, directory services, record locator services and security infrastructure; see [architecture.md](architecture.md#how-this-simplifies-real-qhin-to-qhin-exchange).
- Credentials, the network token key and the **PPRL key are public demo constants**. Hashed identifiers can still be personal data, and real PPRL needs key custody, salting/rotation and legal review.
- Append-only audit is enforced by the API plus a hash chain, not by database permissions or WORM storage. Timestamps come from a deterministic logical clock.
- Treatment matching is deliberately simple (exact family name and DOB plus a standardized given name).

## Policy

- Policy content is descriptive and **not legal advice**. TEFCA documents change often. The versions cited were current on 2026-11-05 according to the RCE resources page, and may since have been superseded.
- Nothing here implies that chronic disease surveillance is an established TEFCA use case; the Public Health SOP lists chronic disease only as a possible future area ([T4]).

[T4]: references.md

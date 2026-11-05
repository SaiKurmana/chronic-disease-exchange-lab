# Policy context: TEFCA, HIPAA public health disclosures, information blocking

> Synthetic data — for demonstration only. Independent portfolio project. Not affiliated with, endorsed by, or produced for CDC, ONC/ASTP, The Sequoia Project, or any QHIN. Not a TEFCA implementation. All data are synthetic.
>
> **Not legal advice.** This page summarizes public sources to explain the design of a simulation. It does not interpret law for any organization. Consult counsel for real implementations. Sources were accessed 2026-11-05 and are listed in [references.md](references.md).

## 1. TEFCA in brief

- **What it is.** The Trusted Exchange Framework and Common Agreement is a nationwide "network of networks" framework. ASTP/ONC sets overall policy. A Recognized Coordinating Entity (RCE) provides oversight; The Sequoia Project serves as RCE under an ONC contract. Qualified Health Information Networks (QHINs) connect directly to each other, and Participants and Subparticipants connect through QHINs ([T10], [T11]). The 21st Century Cures Act directed ONC to develop or support such a framework ([L6], as cited in [T6]).
- **Common Agreement.** The current version listed by the RCE is **Version 2.1 (November 2024)**. Earlier versions were 2.0 (April 2024), 1.1 (November 2023) and 1.0 (January 2022) ([T1], [T2]).
- **QHINs.** The RCE lists designated QHINs on its website ([T8]). This project is **not** a QHIN, does not connect to any QHIN, and does not represent any.
- **Exchange Purposes (XPs).** Six authorized XPs: Treatment, Payment, Health Care Operations, **Public Health**, Government Benefits Determination, and Individual Access Services. Each transaction must carry an XP code, and more specific "Level 2" codes exist for some use cases ([T3], [T7], [T10]).
- **SOPs used by this project:** the Exchange Purposes SOP v5.1 (effective 2026-08-03) [T3], the XP Implementation SOP: Public Health v1.1 (2025-04-25) [T4], and the Facilitated FHIR Implementation SOP v2.0 (effective 2026-03-08) [T5].
- **FHIR roadmap.** The *FHIR Roadmap for TEFCA Exchange* v2 (December 2023) lays out four stages: FHIR content support, QHIN-facilitated FHIR exchange, QHIN-to-QHIN FHIR exchange, and end-to-end FHIR exchange ([T6]). The Facilitated FHIR SOP points FHIR adopters to US Core 6.1.0 or higher and to UDAP-based security ([T5]).

### Public Health under TEFCA, as described in the SOPs

| Topic | What the sources say | How the simulation reflects it |
|---|---|---|
| Definition | Public Health covers requests, uses, disclosures or responses permitted under HIPAA and other applicable law for public health activities involving a Public Health Authority, *including* uses or disclosures under 45 CFR 164.512(b) and 164.514 ([T3], [T4]) | The PHA requester uses `T-PH` |
| XP codes | `T-PH`; Level 2 `T-PH-ECR` (electronic case reporting) and `T-PH-ELR` (electronic lab reporting). The ECR and ELR codes are message delivery/push only, with no queries ([T3]) | `T-PH-ECR`/`T-PH-ELR` queries are refused (`400`) |
| Response obligation | For `T-PH`, "All Responding Nodes SHOULD Respond", and responders may charge fees ([T3]). PHAs are not required to respond to queries ([T4]) | Documented as a completeness risk; the demo nodes always respond |
| Who may query | Only PHAs or their Delegates may conduct QHIN Queries or FHIR Queries under `T-PH` ([T4] §4) | Role check: `PHA` only |
| Query content | PHA queries must include the jurisdiction and a date range. FHIR queries carry the jurisdiction in a `tefca_phj` extension during authorization ([T4] §5.5) | Envelope requires both; jurisdiction must match the directory |
| Minimum response | If a node responds, it SHOULD return at least USCDI v1 classes and elements that it maintains and that were requested ([T4] §5.5.4) | The profile requests a USCDI v3-aligned subset |
| Intermediaries | PH information MUST NOT be persisted or used by nodes along the transaction chain that are not the addressed recipient, except by agreement or for required audit ([T4] §5.4) | Broker outbox is purged on `DELETE`; only the audit log is kept |
| Chronic disease | Named among possible future use cases the RCE may address ([T4] §4) | This project shows what such a use case could look like; it does **not** claim one exists |

**Not verified or out of scope:** This project does not describe any specific QHIN's implementation, fees, or production use of Bulk Data under TEFCA. The Facilitated FHIR SOP does not specify `$export`, so using it here is a design choice of this simulation.

## 2. HIPAA public health disclosures

- **Permission.** A covered entity may disclose PHI without individual authorization to "a public health authority that is authorized by law to collect or receive such information for the purpose of preventing or controlling disease, injury, or disability, including … the conduct of public health surveillance, public health investigations, and public health interventions" (45 CFR 164.512(b)(1)(i); authorization exemption in the section's introduction) ([L1]).
- **Public health authority.** Defined at 45 CFR 164.501. The definition includes agencies of the United States, a State or territory, political subdivisions and Indian tribes, and entities acting under a grant of authority from or a contract with such agencies ([L4]).
- **Minimum necessary.** This applies to most uses, disclosures and requests (45 CFR 164.502(b)) but **not** to disclosures to or requests by a health care provider for treatment (164.502(b)(2)(i)) ([L3]). A covered entity may reasonably rely on a public official's representation that the requested information is the minimum necessary (164.514(d)(3)(iii)(A)) ([L2]). The simulation encodes the agreed minimum-necessary scope as a data profile enforced in the network, which is why `T-PH` and `T-TREAT` return different data.
- **Limited data set.** A limited data set excludes 16 direct identifiers, including names, street address (town/city, State and ZIP may remain), phone and fax numbers, email, SSN, medical record numbers and account numbers. It may be used or disclosed for research, public health or health care operations under a data use agreement (164.514(e)(2)-(4)) ([L2]). The Public Health payload follows this model. Note that a disclosure to a PHA under 164.512(b) does not itself require a limited data set; this project chooses the LDS as a privacy-protective design.
- **Other law.** State law, tribal law, and federal rules such as 42 CFR Part 2 (confidentiality of substance use disorder patient records) [L8] can impose stricter conditions. **[adapt]**

## 3. Information blocking (21st Century Cures Act; 45 CFR Part 171)

- **Definition.** Information blocking is a practice that, except as required by law or covered by an exception, is likely to interfere with access, exchange or use of electronic health information, combined with the knowledge standard that applies to the actor (health IT developers of certified health IT, HINs/HIEs, and health care providers) (45 CFR 171.103) ([L5]).
- **Exceptions.** Part 171 sets out exceptions for not fulfilling requests (Subpart B, 171.200-171.206), for procedures for fulfilling requests (Subpart C, 171.300-171.303), and for practices related to participation in TEFCA (Subpart D, 171.400-171.403). Subpart J addresses disincentives for health care providers ([L5]).
- **Relevance to this use case.** The design choices here are descriptive illustrations, not compliance determinations: refusing out-of-scope purposes, limiting a public health response to minimum necessary, and offering a standards-based manner of access. Whether any practice is information blocking depends on facts, actor type and the applicable exceptions.

## 4. Why purposes return different data (summary)

| | Treatment (`T-TREAT`) | Public Health (`T-PH`) |
|---|---|---|
| Typical requester | Health care provider | Public health authority |
| Granularity | One patient, matched on demographics | Population, over a date range and jurisdiction |
| Identifiers | Included (provider must identify the patient) | Removed (limited data set; pseudonyms + PPRL tokens) |
| Scope | Full record | Value-set and date-range filtered |
| HIPAA minimum necessary | Not applicable to disclosures to providers for treatment (164.502(b)(2)(i)) | Applies; reliance on the public official's representation is permitted (164.514(d)(3)(iii)(A)) |

[T1]: references.md
[T2]: references.md
[T3]: references.md
[T4]: references.md
[T5]: references.md
[T6]: references.md
[T7]: references.md
[T8]: references.md
[T10]: references.md
[T11]: references.md
[L1]: references.md
[L2]: references.md
[L3]: references.md
[L4]: references.md
[L5]: references.md
[L6]: references.md
[L8]: references.md

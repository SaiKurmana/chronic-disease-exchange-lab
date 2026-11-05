"""FHIR R4 structural validation and US Core 'must have' checks.

Synthetic data — for demonstration only.
"""

from collections import Counter

from labcore.io import read_ndjson
from labcore.validate import structural_errors, us_core_errors


def test_source_resources_are_structurally_valid(sim):
    errors = Counter()
    n = 0
    for f in sorted(sim["paths"]["raw"].glob("*/*.ndjson")):
        for r in read_ndjson(f):
            n += 1
            for e in structural_errors(r):
                errors[(f.parent.name, r["resourceType"], e)] += 1
    assert n > 5000
    assert not errors, errors.most_common(5)


def test_us_core_violations_are_only_the_intended_flavor(sim):
    """The independent practice deliberately sends a non-UCUM BP unit ("mmHg")."""
    found = Counter()
    for f in sorted(sim["paths"]["raw"].glob("*/*.ndjson")):
        for r in read_ndjson(f):
            for e in us_core_errors(r):
                found[(f.parent.name, e)] += 1
    assert set(found) <= {("ipp", "BP component unit must be UCUM mm[Hg]")}, found


def test_public_health_payload_is_valid_and_us_core_patient_conformant(sim):
    for f in sorted(sim["paths"]["exchange"].glob("received/*/*.ndjson")):
        for r in read_ndjson(f):
            assert not structural_errors(r), (f, r["id"])
            if r["resourceType"] == "Patient":
                assert not us_core_errors(r), (f, r["id"])  # masked name uses data-absent-reason (us-core-6)


def test_validator_rejects_invalid_resources():
    assert structural_errors({"resourceType": "Patient", "gender": "not-a-gender"})
    assert structural_errors(
        {
            "resourceType": "Observation",
            "status": "final",
            "code": {"text": "x"},
            "subject": {"reference": "Group/1"},
        }
    )
    bad = {
        "resourceType": "Patient",
        "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
        "gender": "female",
    }
    assert "Patient.identifier missing" in us_core_errors(bad)

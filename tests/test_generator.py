"""Synthetic generator: determinism, labeling, duplicates, ground truth.

Synthetic data — for demonstration only.
"""

import hashlib

from labcore import codes as C
from labcore.io import read_csv, read_ndjson
from synth.generate import generate


def _digest(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_generation_is_deterministic(tmp_path):
    generate(120, 99, tmp_path / "a")
    generate(120, 99, tmp_path / "b")
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")
    generate(120, 100, tmp_path / "c")
    assert _digest(tmp_path / "a") != _digest(tmp_path / "c")


def test_every_resource_is_labeled_synthetic(sim):
    for f in sim["paths"]["raw"].glob("*/*.ndjson"):
        for r in read_ndjson(f):
            assert C.SYNTHETIC_TAG in r["meta"]["tag"], f
            assert C.HTEST_SECURITY in r["meta"]["security"], f


def test_cross_org_duplicates_and_ground_truth(sim):
    links = read_csv(sim["paths"]["gt"] / "links.csv", dtype=str)
    persons = read_csv(sim["paths"]["gt"] / "persons.csv", dtype=str)
    assert links["person_id"].nunique() == len(persons)
    multi = links.groupby("person_id").size()
    assert (multi > 1).sum() > 0.05 * len(persons)  # some people are seen at more than one organization
    assert links["patient_id"].is_unique


def test_flavors_present(sim):
    raw = sim["paths"]["raw"]
    rhc = read_ndjson(raw / "rhc" / "Condition.ndjson")
    assert any(c["code"]["coding"][0]["system"] == C.LOCAL_DX_RHC for c in rhc)
    fq = read_ndjson(raw / "fqhc" / "Observation.ndjson")
    assert any(o["code"]["coding"][0]["system"] == C.LOCAL_LAB_FQHC for o in fq)
    ipp = read_ndjson(raw / "ipp" / "MedicationRequest.ndjson")
    assert any("coding" not in m["medicationCodeableConcept"] for m in ipp)

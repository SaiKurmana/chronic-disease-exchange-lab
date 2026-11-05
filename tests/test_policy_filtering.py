"""Purpose-based access control and the Public Health minimum-necessary filter.

Synthetic data — for demonstration only.
"""

from datetime import date

import pytest

from labcore import codes as C
from labcore.io import read_ndjson
from network.policy import PH_RESOURCE_TYPES, VS_CONDITIONS, VS_OBSERVATIONS, check_request

DR = (date(2024, 1, 1), date(2025, 12, 31))


@pytest.mark.parametrize(
    "purpose,role,op,kw,status",
    [
        ("T-PH", "PHA", "bulk-export", {}, 200),
        ("T-PH", "HealthPlan", "bulk-export", {}, 403),
        ("T-PH", "PHA", "patient-query", {}, 403),
        ("T-PH", "PHA", "bulk-export", {"date_range": None}, 400),
        ("T-PH", "PHA", "bulk-export", {"jurisdiction": None}, 400),
        ("T-PH", "PHA", "bulk-export", {"types": ["DocumentReference"]}, 403),
        ("T-PH-ECR", "PHA", "bulk-export", {}, 400),
        ("T-PH-ELR", "PHA", "bulk-export", {}, 400),
        ("T-TREAT", "HealthCareProvider", "patient-query", {}, 200),
        ("T-TREAT", "HealthCareProvider", "bulk-export", {}, 403),
        ("T-TREAT", "PHA", "patient-query", {}, 403),
        ("T-PYMNT", "HealthPlan", "bulk-export", {}, 403),
        ("T-IAS", "IASProvider", "patient-query", {}, 403),
        ("NOPE", "PHA", "bulk-export", {}, 400),
    ],
)
def test_check_request(purpose, role, op, kw, status):
    args = {"jurisdiction": "Lakeland State", "date_range": DR, "types": PH_RESOURCE_TYPES} | kw
    assert check_request(purpose, role, op, **args).http_status == status


def _received(sim, t):
    return [
        r for f in sorted(sim["paths"]["exchange"].glob(f"received/*/{t}.ndjson")) for r in read_ndjson(f)
    ]


def test_ph_payload_has_no_direct_identifiers(sim):
    pats = _received(sim, "Patient")
    assert pats
    for p in pats:
        assert p["id"].startswith("ph-")
        assert "telecom" not in p
        assert all("line" not in a for a in p.get("address", []))
        assert all(not n.get("family") and not n.get("given") for n in p["name"])
        assert all(i["system"].endswith("/sid/ph-pseudonym") for i in p["identifier"])  # no MRNs


def test_ph_payload_respects_value_sets_and_date_range(sim):
    from network.policy import REGISTERED_LOCAL

    for c in _received(sim, "Condition"):
        codes = {(x["system"], x["code"]) for x in c["code"]["coding"]}
        assert codes & (VS_CONDITIONS | REGISTERED_LOCAL)
    for o in _received(sim, "Observation"):
        codes = {(x["system"], x["code"]) for x in o["code"]["coding"]}
        assert codes & (VS_OBSERVATIONS | REGISTERED_LOCAL)
        when = (o.get("effectiveDateTime") or o.get("issued"))[:10]
        assert "2024-01-01" <= when <= "2025-12-31"
    # sensitive / unrelated conditions never leave the node under Public Health
    mdd = C.OTHER_CONDITIONS[3][0][1]
    assert not any(x["code"] == mdd for c in _received(sim, "Condition") for x in c["code"]["coding"])


def test_treatment_returns_identifiers_but_ph_does_not(sim):
    import json

    ex = json.loads(
        (sim["paths"]["examples"] / "02_treatment_patient_query" / "response_bundle.json").read_text()
    )
    pats = [e["resource"] for e in ex["entry"] if e["resource"]["resourceType"] == "Patient"]
    assert pats and all(p["name"][0].get("family") for p in pats)
    assert all(p["identifier"][0]["type"]["coding"][0]["code"] == "MR" for p in pats)


def test_refusals_return_operation_outcomes(sim):
    statuses = {d["slug"]: d["status"] for d in sim["exchange"]["denials"]}
    assert statuses["payer-asserts-public-health"] == 403
    assert statuses["ph-missing-date-range"] == 400
    assert statuses["ph-ecr-query"] == 400
    assert statuses["treatment-bulk-export"] == 403
    assert statuses["invalid-credential"] == 401
    assert statuses["ph-patient-name-query"] == 403

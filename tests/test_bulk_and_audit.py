"""Bulk Data ($export) protocol behavior at a node, and audit-log completeness/integrity.

Synthetic data — for demonstration only.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from network.audit import AuditLog, verify_frame
from network.node import broker_token, create_node_app

H = {
    "X-Request-Id": "t-1",
    "Authorization": f"Bearer {broker_token('t-1')}",
    "X-Exchange-Purpose": "T-PH",
    "Prefer": "respond-async",
}


@pytest.fixture(scope="module")
def node(sim):
    return TestClient(create_node_app("amc", sim["paths"]["raw"]), base_url="https://amc.node.example")


def test_requires_network_token(node):
    assert node.get("/metadata").status_code == 200
    r = node.get("/Patient/$export", headers={"Prefer": "respond-async"})
    assert r.status_code == 401 and r.json()["resourceType"] == "OperationOutcome"


def test_kickoff_requires_prefer_respond_async(node):
    h = {k: v for k, v in H.items() if k != "Prefer"}
    assert node.get("/Patient/$export", headers=h).status_code == 400


def test_bulk_export_lifecycle(node):
    r = node.get("/Patient/$export", params={"_type": "Patient,Observation"}, headers=H)
    assert r.status_code == 202
    status_url = r.headers["Content-Location"]
    assert status_url.startswith("https://amc.node.example/bulkstatus/")
    s1 = node.get(status_url, headers=H)
    assert s1.status_code == 202 and "X-Progress" in s1.headers
    s2 = node.get(status_url, headers=H)
    assert s2.status_code == 200
    m = s2.json()
    for k in ("transactionTime", "request", "requiresAccessToken", "output", "error"):
        assert k in m
    assert {o["type"] for o in m["output"]} == {"Patient", "Observation"}
    f = node.get(m["output"][0]["url"], headers=H)
    assert f.headers["content-type"].startswith("application/fhir+ndjson")
    assert len(f.text.strip().splitlines()) == m["output"][0]["count"]
    assert node.delete(status_url, headers=H).status_code == 202
    assert node.get(status_url, headers=H).status_code == 404


def test_unsupported_type_is_rejected(node):
    r = node.get(
        "/Patient/$export",
        params={"_type": "Group"},
        headers={**H, "X-Request-Id": "t-2", "Authorization": f"Bearer {broker_token('t-2')}"},
    )
    assert r.status_code == 400


def test_every_request_is_audited(sim):
    audit = pd.read_csv(sim["paths"]["outputs"] / "audit_log.csv", comment="#")
    ok, msg = verify_frame(audit)
    assert ok, msg
    by_req = audit.groupby("request_id")["event_type"].apply(set)
    expected_requests = 2 + len(sim["exchange"]["denials"])
    assert len(by_req) == expected_requests
    for events in by_req:
        assert {"request.received", "request.decision"} <= events
    bulk = audit[audit.request_id == "req-0001-ph-bulk"]
    nodes = set(bulk.loc[bulk.event_type == "node.export", "target_node"])
    assert nodes == {"amc", "fqhc", "ipp", "mmg", "rhc"}
    assert (bulk.event_type == "broker.min_necessary_filter").sum() == 5
    for col in ("requester_id", "purpose_code", "operation", "event_time", "outcome"):
        assert audit[col].notna().all(), col
    denied = audit[(audit.event_type == "request.decision") & (audit.outcome == "denied")]
    assert len(denied) == len(sim["exchange"]["denials"])


def test_audit_chain_detects_tampering():
    log = AuditLog()
    for i in range(5):
        log.append(
            request_id=f"r{i}",
            event_type="request.received",
            requester_id="x",
            purpose_code="T-PH",
            operation="bulk-export",
            outcome="received",
            http_status=0,
        )
    df = log.df()
    assert verify_frame(df)[0]
    edited = df.copy()
    edited.loc[2, "requester_id"] = "someone-else"
    assert not verify_frame(edited)[0]
    dropped = df.drop(index=3).reset_index(drop=True)
    assert not verify_frame(dropped)[0]
    assert not hasattr(log, "update") and not hasattr(log, "delete")

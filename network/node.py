"""A minimal FHIR-like API for one simulated healthcare organization ("node").

Endpoints (subset of FHIR R4 REST + Bulk Data Access v2.0.0 patterns):
  GET    /metadata                                  CapabilityStatement
  GET    /Patient?family=&given=&birthdate=         searchset Bundle (demographic match)
  GET    /{type}?patient={id}                       searchset Bundle (Condition, Observation, ...)
  GET    /Patient/$export?_type=&_since=            Bulk kick-off -> 202 + Content-Location
  GET    /bulkstatus/{job}                          202 (X-Progress, Retry-After) then 200 manifest
  GET    /bulkfiles/{job}/{type}.ndjson             application/fhir+ndjson
  DELETE /bulkstatus/{job}                          202, then status -> 404

Every request must carry the broker-issued bearer token and the declared exchange purpose.
Only resources whose meta.lastUpdated <= the node's "as of" date are visible (timeliness).

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import hashlib
import hmac
from collections import defaultdict
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from labcore.config import DATA_AS_OF, SYNTHETIC_LABEL
from labcore.io import read_ndjson, to_ndjson
from labcore.pprl import patient_tokens, standardize_given
from synth.orgs import ORG_BY_ID

from .policy import LINKAGE_EXT

RESOURCE_TYPES = ["Patient", "Encounter", "Condition", "Observation", "MedicationRequest"]
BROKER_KEY = b"simulated-broker-signing-key (demo only)"
FHIR_JSON = "application/fhir+json"
NDJSON = "application/fhir+ndjson"


def broker_token(request_id: str) -> str:
    """Stand-in for a network-issued access token (real networks use mTLS + signed JWTs)."""
    return hmac.new(BROKER_KEY, request_id.encode(), hashlib.sha256).hexdigest()


def operation_outcome(status: int, code: str, text: str) -> JSONResponse:
    return JSONResponse(
        {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": code, "diagnostics": text}],
        },
        status_code=status,
        media_type=FHIR_JSON,
    )


class NodeStore:
    def __init__(self, org_id: str, raw_dir: Path, as_of: date = DATA_AS_OF):
        self.org_id = org_id
        self.as_of = as_of
        self.by_type: dict[str, list[dict]] = {}
        self.pending: dict[str, int] = {}
        cutoff = f"{as_of.isoformat()}T23:59:59Z"
        for t in RESOURCE_TYPES + ["Organization"]:
            rows = read_ndjson(raw_dir / org_id / f"{t}.ndjson")
            visible = [r for r in rows if r.get("meta", {}).get("lastUpdated", "") <= cutoff]
            self.by_type[t] = visible
            self.pending[t] = len(rows) - len(visible)
        self.by_patient: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for t in RESOURCE_TYPES[1:]:
            for r in self.by_type[t]:
                pid = r.get("subject", {}).get("reference", "").split("/", 1)[-1]
                self.by_patient[pid][t].append(r)
        self.patients = {p["id"]: p for p in self.by_type["Patient"]}


def searchset(resources: list[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "meta": {"tag": [{"code": "synthetic", "display": SYNTHETIC_LABEL}]},
        "entry": [{"resource": r, "search": {"mode": "match"}} for r in resources],
    }


def create_node_app(org_id: str, raw_dir: Path, as_of: date = DATA_AS_OF) -> FastAPI:
    org = ORG_BY_ID[org_id]
    store = NodeStore(org_id, raw_dir, as_of)
    app = FastAPI(title=f"{org.name} (simulated node)", description=SYNTHETIC_LABEL)
    app.state.store = store
    jobs: dict[str, dict] = {}

    @app.middleware("http")
    async def require_network_auth(request: Request, call_next):
        rid = request.headers.get("X-Request-Id", "")
        auth = request.headers.get("Authorization", "")
        if request.url.path != "/metadata":
            if not rid or auth != f"Bearer {broker_token(rid)}":
                return operation_outcome(401, "login", "Missing or invalid network access token")
            if not request.headers.get("X-Exchange-Purpose"):
                return operation_outcome(400, "required", "X-Exchange-Purpose header is required")
        return await call_next(request)

    @app.get("/metadata")
    def metadata():
        return JSONResponse(
            {
                "resourceType": "CapabilityStatement",
                "status": "active",
                "kind": "instance",
                "date": "2026-01-01",
                "fhirVersion": "4.0.1",
                "format": ["json"],
                "software": {"name": f"{org.id}-simulated-node"},
                "implementation": {"description": f"{org.name} — {SYNTHETIC_LABEL}"},
                "instantiates": ["http://hl7.org/fhir/uv/bulkdata/CapabilityStatement/bulk-data"],
                "rest": [
                    {
                        "mode": "server",
                        "resource": [
                            {"type": t, "interaction": [{"code": "search-type"}]} for t in RESOURCE_TYPES
                        ],
                        "operation": [
                            {
                                "name": "export",
                                "definition": "http://hl7.org/fhir/uv/bulkdata/OperationDefinition/patient-export",
                            }
                        ],
                    }
                ],
            },
            media_type=FHIR_JSON,
        )

    @app.get("/Patient")
    def patient_search(family: str = "", given: str = "", birthdate: str = ""):
        if not (family and birthdate):
            return operation_outcome(400, "required", "family and birthdate are required")
        fam = family.strip().upper()
        g = standardize_given(given)
        hits = [
            p
            for p in store.patients.values()
            if p.get("birthDate") == birthdate
            and (p.get("name") or [{}])[0].get("family", "").upper() == fam
            and (not g or standardize_given((p["name"][0].get("given") or [""])[0]) == g)
        ]
        return JSONResponse(searchset(sorted(hits, key=lambda r: r["id"])), media_type=FHIR_JSON)

    @app.get("/{rtype}")
    def type_search(rtype: str, patient: str = ""):
        if rtype not in RESOURCE_TYPES[1:]:
            return operation_outcome(404, "not-supported", f"Unsupported resource type {rtype}")
        if not patient:
            return operation_outcome(400, "required", "patient parameter is required")
        pid = patient.split("/")[-1]
        return JSONResponse(searchset(store.by_patient.get(pid, {}).get(rtype, [])), media_type=FHIR_JSON)

    @app.get("/Patient/$export")
    def export_kickoff(request: Request, _type: str = "", _since: str = "", _outputFormat: str = NDJSON):
        if request.headers.get("Prefer", "") != "respond-async":
            return operation_outcome(400, "required", "Prefer: respond-async header is required")
        if _outputFormat not in (NDJSON, "application/ndjson", "ndjson"):
            return operation_outcome(400, "not-supported", f"Unsupported _outputFormat {_outputFormat}")
        types = [t for t in _type.split(",") if t] or RESOURCE_TYPES
        unsupported = [t for t in types if t not in RESOURCE_TYPES]
        if unsupported:
            return operation_outcome(400, "not-supported", f"Unsupported _type values: {unsupported}")
        rid = request.headers["X-Request-Id"]
        job = f"{org.id}-{hashlib.sha256(rid.encode()).hexdigest()[:12]}"
        purpose = request.headers["X-Exchange-Purpose"]
        files = {}
        for t in types:
            rows = [r for r in store.by_type[t] if not _since or r["meta"]["lastUpdated"] > _since]
            if t == "Patient" and purpose == "T-PH":
                # data-source-side PPRL tokenization (identifiers never leave the node in clear text
                # once the broker's minimum-necessary filter is applied)
                rows = [_with_tokens(p) for p in rows]
            files[t] = rows
        jobs[job] = {"request": str(request.url), "files": files, "polls": 0}
        status_url = f"{str(request.base_url).rstrip('/')}/bulkstatus/{job}"
        return Response(status_code=202, headers={"Content-Location": status_url})

    @app.get("/bulkstatus/{job}")
    def export_status(job: str, request: Request):
        if job not in jobs:
            return operation_outcome(404, "not-found", f"Unknown or deleted export job {job}")
        j = jobs[job]
        j["polls"] += 1
        if j["polls"] == 1:  # deterministic: first poll reports in-progress
            return Response(status_code=202, headers={"X-Progress": "in progress", "Retry-After": "1"})
        base = str(request.base_url).rstrip("/")
        return JSONResponse(
            {
                "transactionTime": f"{store.as_of.isoformat()}T23:59:59Z",
                "request": j["request"],
                "requiresAccessToken": True,
                "output": [
                    {"type": t, "url": f"{base}/bulkfiles/{job}/{t}.ndjson", "count": len(rows)}
                    for t, rows in j["files"].items()
                    if rows
                ],
                "error": [],
                "extension": {"synthetic-data": SYNTHETIC_LABEL},
            },
            media_type="application/json",
        )

    @app.get("/bulkfiles/{job}/{fname}")
    def export_file(job: str, fname: str):
        t = fname.removesuffix(".ndjson")
        if job not in jobs or t not in jobs[job]["files"]:
            return operation_outcome(404, "not-found", "File not found")
        return Response(to_ndjson(jobs[job]["files"][t]), media_type=NDJSON)

    @app.delete("/bulkstatus/{job}")
    def export_delete(job: str):
        if jobs.pop(job, None) is None:
            return operation_outcome(404, "not-found", f"Unknown export job {job}")
        return Response(status_code=202)

    return app


def _with_tokens(p: dict) -> dict:
    out = dict(p)
    toks = patient_tokens(p)
    ext = [e for e in p.get("extension", []) if e.get("url") != LINKAGE_EXT]
    ext.append(
        {"url": LINKAGE_EXT, "extension": [{"url": k, "valueString": v} for k, v in sorted(toks.items())]}
    )
    out["extension"] = ext
    return out

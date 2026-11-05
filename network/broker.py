"""Simulated network broker: authenticate requester -> check exchange purpose -> route to nodes ->
apply minimum-necessary filter (Public Health) -> relay -> audit every step.

This deliberately collapses several real-world layers (QHIN-to-QHIN routing, record locator
services, directory services, UDAP/SMART security, responder-side policy engines) into one
in-process component. See docs/architecture.md, "How this simplifies real exchange".

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

from labcore.config import DATA_AS_OF, RAW_DIR, SYNTHETIC_LABEL
from labcore.io import parse_ndjson, to_ndjson
from synth.orgs import ORGS

from .audit import AuditLog
from .node import BROKER_KEY, NDJSON, broker_token, create_node_app
from .policy import (
    FILTER_PROFILE_PH,
    PH_RESOURCE_TYPES,
    XP_CODES,
    check_request,
    ph_filter_resource,
    treatment_view,
)

BROKER_BASE = "https://broker.network.example"

# Simulated participant directory (credentials are demo placeholders, not secrets).
REQUESTERS = {
    "lkdph": {
        "name": "Lakeland Department of Public Health (fictional)",
        "role": "PHA",
        "jurisdiction": "Lakeland State",
        "credential": "demo-credential-lkdph",
    },
    "amc-clinician": {
        "name": "Clinician at Lakeland Academic Medical Center",
        "role": "HealthCareProvider",
        "org": "amc",
        "credential": "demo-credential-amc",
    },
    "acme-health-plan": {
        "name": "Acme Health Plan (fictional)",
        "role": "HealthPlan",
        "credential": "demo-credential-plan",
    },
}


@dataclass
class Envelope:
    """The request envelope defined in docs/data_sharing_protocol.md."""

    request_id: str
    requester_id: str
    credential: str
    purpose: str
    operation: str
    jurisdiction: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    types: list[str] = field(default_factory=list)
    patient: dict = field(default_factory=dict)  # family, given, birthdate (patient-query only)
    targets: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_json(cls, d: dict) -> Envelope:
        dr = d.get("date_range") or {}
        return cls(
            request_id=d.get("request_id", ""),
            requester_id=d.get("requester", {}).get("id", ""),
            credential=d.get("requester", {}).get("credential", ""),
            purpose=d.get("purpose", ""),
            operation=d.get("operation", ""),
            jurisdiction=d.get("jurisdiction"),
            date_start=dr.get("start"),
            date_end=dr.get("end"),
            types=d.get("resource_types", []),
            patient=d.get("patient", {}),
            targets=d.get("targets", ["*"]),
        )

    def to_json(self, redact: bool = True) -> dict:
        out = {
            "request_id": self.request_id,
            "requester": {"id": self.requester_id, "credential": "***" if redact else self.credential},
            "purpose": self.purpose,
            "operation": self.operation,
            "targets": self.targets,
        }
        if self.jurisdiction:
            out["jurisdiction"] = self.jurisdiction
        if self.date_start or self.date_end:
            out["date_range"] = {"start": self.date_start, "end": self.date_end}
        if self.types:
            out["resource_types"] = self.types
        if self.patient:
            out["patient"] = self.patient
        return out


def ph_pseudonym(requester_id: str, node: str, patient_id: str) -> str:
    """Opaque, requester-specific, stable patient pseudonym used in Public Health responses."""
    msg = f"{requester_id}|{node}|{patient_id}".encode()
    return "ph-" + hmac.new(BROKER_KEY, msg, hashlib.sha256).hexdigest()[:16]


def _oo(status: int, code: str, text: str) -> dict:
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": code, "diagnostics": text}],
        "_http_status": status,
    }


class Broker:
    def __init__(
        self,
        raw_dir: Path = RAW_DIR,
        audit: AuditLog | None = None,
        as_of: date = DATA_AS_OF,
        org_ids: list[str] | None = None,
    ):
        self.audit = audit or AuditLog()
        self.nodes: dict[str, TestClient] = {}
        for o in ORGS:
            if org_ids and o.id not in org_ids:
                continue
            app = create_node_app(o.id, raw_dir, as_of)
            self.nodes[o.id] = TestClient(app, base_url=f"https://{o.id}.node.example")
        self.outbox: dict[str, dict] = {}

    # ------------------------------------------------------------------------------------------
    def directory(self) -> dict:
        return {
            "nodes": [
                {
                    "id": o.id,
                    "name": o.name,
                    "kind": o.kind,
                    "county": o.county,
                    "ehr_flavor": o.ehr_label,
                    "fhir_base": f"https://{o.id}.node.example",
                    "fhir_version": "4.0.1",
                    "supports": ["patient-query", "bulk-export"],
                }
                for o in ORGS
                if o.id in self.nodes
            ],
            "requesters": [{"id": k, "name": v["name"], "role": v["role"]} for k, v in REQUESTERS.items()],
            "purposes_supported": {
                "T-PH": "bulk-export (population, limited data set)",
                "T-TREAT": "patient-query (full record)",
            },
        }

    def _log(
        self,
        env: Envelope,
        event: str,
        outcome: str,
        status: int,
        *,
        node: str = "",
        returned: int = 0,
        withheld: int = 0,
        detail: str = "",
    ) -> None:
        req = REQUESTERS.get(env.requester_id, {})
        self.audit.append(
            request_id=env.request_id,
            event_type=event,
            requester_id=env.requester_id or "(none)",
            requester_role=req.get("role", "unknown"),
            purpose_code=env.purpose,
            operation=env.operation,
            target_node=node,
            resource_types=",".join(env.types),
            jurisdiction=env.jurisdiction or "",
            date_range=f"{env.date_start or ''}/{env.date_end or ''}"
            if (env.date_start or env.date_end)
            else "",
            outcome=outcome,
            http_status=status,
            records_returned=returned,
            records_withheld=withheld,
            detail=detail,
        )

    def _authorize(self, env: Envelope) -> dict | None:
        """Return an OperationOutcome dict if the request must be refused, else None."""
        self._log(env, "request.received", "received", 0, detail=f"purpose={XP_CODES.get(env.purpose, '?')}")
        req = REQUESTERS.get(env.requester_id)
        if not req or not hmac.compare_digest(req["credential"], env.credential or ""):
            self._log(
                env, "request.decision", "denied", 401, detail="unknown requester or invalid credential"
            )
            return _oo(401, "login", "Unknown requester or invalid credential")
        dr = None
        if env.date_start and env.date_end:
            try:
                dr = (date.fromisoformat(env.date_start), date.fromisoformat(env.date_end))
            except ValueError:
                self._log(env, "request.decision", "denied", 400, detail="unparseable date range")
                return _oo(400, "value", "Unparseable date range")
        dec = check_request(
            env.purpose,
            req["role"],
            env.operation,
            jurisdiction=env.jurisdiction,
            date_range=dr,
            types=env.types,
        )
        if not dec.allowed:
            self._log(env, "request.decision", "denied", dec.http_status, detail=dec.reason)
            return _oo(dec.http_status, dec.issue_code, dec.reason)
        if env.purpose == "T-PH" and env.jurisdiction != req.get("jurisdiction"):
            reason = "Asserted jurisdiction does not match the PHA's registered jurisdiction"
            self._log(env, "request.decision", "denied", 403, detail=reason)
            return _oo(403, "forbidden", reason)
        self._log(env, "request.decision", "permitted", 200, detail=dec.reason)
        return None

    def _targets(self, env: Envelope) -> list[str]:
        return (
            sorted(self.nodes) if env.targets in (["*"], []) else [t for t in env.targets if t in self.nodes]
        )

    def _headers(self, env: Envelope) -> dict:
        return {
            "Authorization": f"Bearer {broker_token(env.request_id)}",
            "X-Request-Id": env.request_id,
            "X-Exchange-Purpose": env.purpose,
            "X-Requester-Id": env.requester_id,
            "Accept": "application/fhir+json",
        }

    def _pseudonymizer(self, env: Envelope, node: str):
        return lambda pid: ph_pseudonym(env.requester_id, node, pid)

    # ---- Population-level bulk export (Public Health) ----------------------------------------
    def bulk_export(self, env: Envelope) -> tuple[int, dict]:
        refusal = self._authorize(env)
        if refusal:
            return refusal.pop("_http_status"), refusal
        start, end = date.fromisoformat(env.date_start), date.fromisoformat(env.date_end)
        types = env.types or PH_RESOURCE_TYPES
        job = "job-" + hashlib.sha256(env.request_id.encode()).hexdigest()[:12]
        out_files: dict[tuple[str, str], list[dict]] = {}
        node_summ = []
        for node in self._targets(env):
            cli = self.nodes[node]
            h = {**self._headers(env), "Prefer": "respond-async"}
            r = cli.get(
                "/Patient/$export", params={"_type": ",".join(types), "_outputFormat": NDJSON}, headers=h
            )
            if r.status_code != 202:
                self._log(env, "node.export", "error", r.status_code, node=node, detail=r.text[:200])
                continue
            status_url = r.headers["Content-Location"]
            polls = 0
            while True:
                polls += 1
                s = cli.get(status_url, headers=h)
                if s.status_code != 202:
                    break
            manifest = s.json()
            self._log(
                env,
                "node.export",
                "completed",
                s.status_code,
                node=node,
                returned=sum(o.get("count", 0) for o in manifest["output"]),
                detail=f"kick-off 202; {polls} status polls; {len(manifest['output'])} files",
            )
            pseudo = self._pseudonymizer(env, node)
            kept_n, dropped = 0, Counter()
            for o in manifest["output"]:
                rows = parse_ndjson(cli.get(o["url"], headers={**h, "Accept": NDJSON}).text)
                kept = []
                for res in rows:
                    fr, why = ph_filter_resource(res, start, end, pseudo)
                    if fr is None:
                        dropped[why] += 1
                    else:
                        kept.append(fr)
                out_files[(node, o["type"])] = sorted(kept, key=lambda x: x["id"])
                kept_n += len(kept)
            cli.delete(status_url, headers=h)
            self._log(
                env,
                "broker.min_necessary_filter",
                "applied",
                200,
                node=node,
                returned=kept_n,
                withheld=sum(dropped.values()),
                detail=f"profile={FILTER_PROFILE_PH}; withheld=" + json.dumps(dict(sorted(dropped.items()))),
            )
            node_summ.append({"node": node, "returned": kept_n, "withheld": dict(sorted(dropped.items()))})
        self.outbox[job] = {"env": env, "files": out_files, "nodes": node_summ}
        self._log(
            env,
            "response.ready",
            "accepted",
            202,
            returned=sum(n["returned"] for n in node_summ),
            withheld=sum(sum(n["withheld"].values()) for n in node_summ),
            detail=f"job={job}",
        )
        return 202, {"job": job, "Content-Location": f"{BROKER_BASE}/exchange/status/{job}"}

    def bulk_status(self, job: str) -> tuple[int, dict]:
        if job not in self.outbox:
            return 404, _oo(404, "not-found", f"Unknown or deleted job {job}")
        j = self.outbox[job]
        env: Envelope = j["env"]
        manifest = {
            "transactionTime": f"{DATA_AS_OF.isoformat()}T23:59:59Z",
            "request": f"{BROKER_BASE}/exchange/$export (request_id={env.request_id})",
            "requiresAccessToken": True,
            "output": [
                {"type": t, "url": f"{BROKER_BASE}/exchange/files/{job}/{n}/{t}.ndjson", "count": len(rows)}
                for (n, t), rows in sorted(j["files"].items())
                if rows
            ],
            "error": [],
            "extension": {
                "purpose": env.purpose,
                "filter_profile": FILTER_PROFILE_PH,
                "nodes": j["nodes"],
                "synthetic-data": SYNTHETIC_LABEL,
            },
        }
        self._log(
            env, "response.manifest", "delivered", 200, returned=sum(o["count"] for o in manifest["output"])
        )
        return 200, manifest

    def bulk_file(self, job: str, node: str, rtype: str) -> tuple[int, str]:
        j = self.outbox.get(job)
        if not j or (node, rtype) not in j["files"]:
            return 404, ""
        rows = j["files"][(node, rtype)]
        self._log(j["env"], "response.file", "delivered", 200, node=node, returned=len(rows), detail=rtype)
        return 200, to_ndjson(rows)

    def bulk_delete(self, job: str) -> int:
        j = self.outbox.pop(job, None)
        if j is None:
            return 404
        self._log(j["env"], "response.deleted", "purged", 202, detail="broker outbox purged (no persistence)")
        return 202

    # ---- Patient-level query (Treatment) -----------------------------------------------------
    def patient_query(self, env: Envelope) -> tuple[int, dict]:
        refusal = self._authorize(env)
        if refusal:
            return refusal.pop("_http_status"), refusal
        q = env.patient
        entries, per_node = [], []
        for node in self._targets(env):
            cli = self.nodes[node]
            h = self._headers(env)
            r = cli.get(
                "/Patient",
                params={
                    "family": q.get("family", ""),
                    "given": q.get("given", ""),
                    "birthdate": q.get("birthdate", ""),
                },
                headers=h,
            )
            if r.status_code != 200:
                self._log(env, "node.query", "error", r.status_code, node=node, detail=r.text[:200])
                continue
            pats = [e["resource"] for e in r.json().get("entry", [])]
            n = 0
            for p in pats:
                entries.append({"resource": treatment_view(p), "extension": {"node": node}})
                n += 1
                for t in ("Condition", "Observation", "MedicationRequest", "Encounter"):
                    b = cli.get(f"/{t}", params={"patient": p["id"]}, headers=h).json()
                    for e in b.get("entry", []):
                        entries.append(
                            {"resource": treatment_view(e["resource"]), "extension": {"node": node}}
                        )
                        n += 1
            self._log(
                env,
                "node.query",
                "completed",
                200,
                node=node,
                returned=n,
                detail=f"{len(pats)} matching patient record(s)",
            )
            per_node.append({"node": node, "matched_patients": len(pats), "resources": n})
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "total": len(entries),
            "meta": {"tag": [{"code": "synthetic", "display": SYNTHETIC_LABEL}]},
            "entry": [
                {
                    "fullUrl": f"https://{e['extension']['node']}.node.example/"
                    f"{e['resource']['resourceType']}/{e['resource']['id']}",
                    "resource": e["resource"],
                }
                for e in entries
            ],
        }
        self._log(env, "response.delivered", "delivered", 200, returned=len(entries))
        return 200, {"bundle": bundle, "summary": per_node}


def create_broker_app(broker: Broker) -> FastAPI:
    app = FastAPI(title="Simulated network broker", description=SYNTHETIC_LABEL)
    app.state.broker = broker

    @app.get("/directory")
    def directory():
        return broker.directory()

    @app.post("/exchange/$export")
    async def kickoff(request: Request):
        env = Envelope.from_json(await request.json())
        status, body = broker.bulk_export(env)
        if status == 202:
            return Response(status_code=202, headers={"Content-Location": body["Content-Location"]})
        return JSONResponse(body, status_code=status, media_type="application/fhir+json")

    @app.get("/exchange/status/{job}")
    def status(job: str):
        code, body = broker.bulk_status(job)
        return JSONResponse(
            body, status_code=code, media_type="application/json" if code == 200 else "application/fhir+json"
        )

    @app.get("/exchange/files/{job}/{node}/{fname}")
    def file(job: str, node: str, fname: str):
        code, text = broker.bulk_file(job, node, fname.removesuffix(".ndjson"))
        return Response(text, status_code=code, media_type=NDJSON)

    @app.delete("/exchange/status/{job}")
    def delete(job: str):
        return Response(status_code=broker.bulk_delete(job))

    @app.post("/exchange/patient-query")
    async def pq(request: Request):
        env = Envelope.from_json(await request.json())
        code, body = broker.patient_query(env)
        if code != 200:
            return JSONResponse(body, status_code=code, media_type="application/fhir+json")
        return JSONResponse(
            body["bundle"],
            media_type="application/fhir+json",
            headers={"X-Node-Summary": json.dumps(body["summary"])},
        )

    return app

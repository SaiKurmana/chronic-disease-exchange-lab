"""`make exchange`: run the use-case flows end to end through the simulated network.

Flow A (Public Health, T-PH): the health department requests a limited data set via bulk export
from every node -> broker applies minimum-necessary filter -> PHA downloads NDJSON -> normalize to
US Core / USCDI elements -> map local codes -> deduplicate across organizations (PPRL tokens).

Flow B (Treatment, T-TREAT): a clinician queries the network for one patient's full record,
for contrast with what Public Health receives for the same person.

Also exercises refusal paths (wrong role, missing date range, push-only XP, ...) so the audit log
shows denials. Writes analytic tables (data/exchange), outputs/, and examples/.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import duckdb
import pandas as pd
from fastapi.testclient import TestClient

from labcore.config import (
    DATA_AS_OF,
    DATA_DIR,
    EXAMPLES_DIR,
    HISTORY_START,
    MP_END,
    OUTPUTS_DIR,
    SYNTHETIC_LABEL,
)
from labcore.io import parse_ndjson, read_csv, write_csv, write_json, write_ndjson
from network.audit import AuditLog
from network.broker import BROKER_BASE, Broker, create_broker_app, ph_pseudonym
from network.policy import PH_RESOURCE_TYPES

from .evaluate import evaluate_linkage, truth_crosswalk
from .linkage import link
from .normalize import Tables, normalize

PHA = {"id": "lkdph", "credential": "demo-credential-lkdph"}
CLINICIAN = {"id": "amc-clinician", "credential": "demo-credential-amc"}
PLAN = {"id": "acme-health-plan", "credential": "demo-credential-plan"}


def ph_envelope(rid: str, **over) -> dict:
    env = {
        "request_id": rid,
        "requester": dict(PHA),
        "purpose": "T-PH",
        "operation": "bulk-export",
        "jurisdiction": "Lakeland State",
        "date_range": {"start": HISTORY_START.isoformat(), "end": MP_END.isoformat()},
        "resource_types": PH_RESOURCE_TYPES,
        "targets": ["*"],
    }
    env.update(over)
    return env


def _path(url: str) -> str:
    return url.replace(BROKER_BASE, "")


def flow_a(client: TestClient) -> tuple[dict, dict, dict]:
    """Public Health bulk export via the broker. Returns (received, transcript, manifest)."""
    env = ph_envelope("req-0001-ph-bulk")
    r = client.post("/exchange/$export", json=env)
    assert r.status_code == 202, r.text
    status_url = r.headers["Content-Location"]
    manifest = client.get(_path(status_url)).json()
    received: dict[str, dict[str, list[dict]]] = {}
    for o in manifest["output"]:
        node = o["url"].split("/")[-2]
        rows = parse_ndjson(client.get(_path(o["url"])).text)
        received.setdefault(node, {})[o["type"]] = rows
    deleted = client.delete(_path(status_url)).status_code
    transcript = {
        "request": env,
        "kickoff": {"status": r.status_code, "Content-Location": status_url},
        "delete_status": deleted,
    }
    return received, transcript, manifest


def pick_coordination_person(gt_dir: Path) -> pd.Series:
    persons = read_csv(gt_dir / "persons.csv", dtype=str)
    links = read_csv(gt_dir / "links.csv", dtype=str).fillna("")
    multi = links.groupby("person_id").filter(
        lambda g: len(g) >= 2 and "amc" in set(g["org_id"]) and (g["variations"] == "").all()
    )
    cand = persons[
        persons["person_id"].isin(multi["person_id"])
        & (persons["htn_diagnosed"] == "True")
        & (persons["age"].astype(int).between(40, 80))
    ]
    return cand.sort_values("person_id").iloc[0]


def flow_b(client: TestClient, raw_dir: Path, gt_dir: Path) -> tuple[dict, dict]:
    p = pick_coordination_person(gt_dir)
    links = read_csv(gt_dir / "links.csv", dtype=str).fillna("")
    amc_pid = links[(links.person_id == p.person_id) & (links.org_id == "amc")].patient_id.iloc[0]
    amc_patient = next(
        x for x in parse_ndjson((raw_dir / "amc" / "Patient.ndjson").read_text()) if x["id"] == amc_pid
    )
    env = {
        "request_id": "req-0002-treatment-query",
        "requester": dict(CLINICIAN),
        "purpose": "T-TREAT",
        "operation": "patient-query",
        "targets": ["*"],
        "patient": {
            "family": amc_patient["name"][0]["family"],
            "given": amc_patient["name"][0]["given"][0],
            "birthdate": amc_patient["birthDate"],
        },
    }
    r = client.post("/exchange/patient-query", json=env)
    return {
        "request": env,
        "status": r.status_code,
        "summary": json.loads(r.headers.get("X-Node-Summary", "[]")),
        "bundle": r.json(),
    }, {"person_id": p.person_id, "links": links[links.person_id == p.person_id]}


DENIALS = [
    (
        "payer-asserts-public-health",
        "A health plan asserts the Public Health purpose",
        lambda: ph_envelope("req-0101-deny", requester=dict(PLAN)),
    ),
    (
        "ph-missing-date-range",
        "PHA omits the required date range",
        lambda: {k: v for k, v in ph_envelope("req-0102-deny").items() if k != "date_range"},
    ),
    (
        "ph-ecr-query",
        "PHA queries using T-PH-ECR (push/message-delivery only)",
        lambda: ph_envelope("req-0103-deny", purpose="T-PH-ECR"),
    ),
    (
        "treatment-bulk-export",
        "Clinician requests a population bulk export under Treatment",
        lambda: ph_envelope("req-0104-deny", requester=dict(CLINICIAN), purpose="T-TREAT"),
    ),
    (
        "ph-excess-resource-types",
        "PHA requests resource types beyond the minimum-necessary profile",
        lambda: ph_envelope("req-0105-deny", resource_types=PH_RESOURCE_TYPES + ["DocumentReference"]),
    ),
    (
        "ph-wrong-jurisdiction",
        "PHA asserts a jurisdiction it is not registered for",
        lambda: ph_envelope("req-0106-deny", jurisdiction="Another State"),
    ),
    (
        "payment-purpose",
        "Health plan requests data for Payment (not supported in this simulated network)",
        lambda: ph_envelope("req-0107-deny", requester=dict(PLAN), purpose="T-PYMNT"),
    ),
    ("unknown-purpose", "Unknown purpose code", lambda: ph_envelope("req-0108-deny", purpose="T-RESEARCH")),
    (
        "invalid-credential",
        "Request with an invalid credential",
        lambda: ph_envelope("req-0109-deny", requester={"id": "lkdph", "credential": "wrong"}),
    ),
]
PH_PATIENT_QUERY_DENIAL = (
    "ph-patient-name-query",
    "PHA attempts a patient-level name search under Public Health",
)


def run_denials(client: TestClient) -> list[dict]:
    out = []
    for slug, desc, mk in DENIALS:
        env = mk()
        r = client.post("/exchange/$export", json=env)
        out.append(
            {
                "slug": slug,
                "description": desc,
                "endpoint": "POST /exchange/$export",
                "request": env,
                "status": r.status_code,
                "response": r.json(),
            }
        )
    env = {
        "request_id": "req-0110-deny",
        "requester": dict(PHA),
        "purpose": "T-PH",
        "operation": "patient-query",
        "jurisdiction": "Lakeland State",
        "date_range": {"start": "2025-01-01", "end": "2025-12-31"},
        "patient": {"family": "Smith", "given": "Mary", "birthdate": "1960-01-01"},
    }
    r = client.post("/exchange/patient-query", json=env)
    out.append(
        {
            "slug": PH_PATIENT_QUERY_DENIAL[0],
            "description": PH_PATIENT_QUERY_DENIAL[1],
            "endpoint": "POST /exchange/patient-query",
            "request": env,
            "status": r.status_code,
            "response": r.json(),
        }
    )
    return out


def save_tables(con: duckdb.DuckDBPyConnection, prefix: str, t: Tables) -> None:
    for name in ("patients", "encounters", "conditions", "bp", "a1c", "meds"):
        df = getattr(t, name)  # noqa: F841 (referenced by DuckDB replacement scan)
        con.execute(f"CREATE OR REPLACE TABLE {prefix}_{name} AS SELECT * FROM df")


def run(
    raw_dir: Path, gt_dir: Path, exchange_dir: Path, outputs_dir: Path, examples_dir: Path | None
) -> dict:
    exchange_dir.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(exchange_dir / "audit.duckdb")
    broker = Broker(raw_dir, audit=audit, as_of=DATA_AS_OF)
    client = TestClient(create_broker_app(broker), base_url=BROKER_BASE)

    received, transcript_a, manifest = flow_a(client)
    for node, by_type in received.items():
        for t, rows in by_type.items():
            write_ndjson(exchange_dir / "received" / node / f"{t}.ndjson", rows)
    flow_b_result, b_truth = flow_b(client, raw_dir, gt_dir)
    denials = run_denials(client)

    mapped = normalize(received, map_codes=True)
    unmapped = normalize(received, map_codes=False)
    xw_link, pairs = link(mapped.patients)
    truth = truth_crosswalk(gt_dir)
    xw_oracle = truth[["node", "patient_key", "person_id"]].rename(columns={"person_id": "person_key"})
    dedup = evaluate_linkage(xw_link, truth)

    db = exchange_dir / "analytic.duckdb"
    if db.exists():
        db.unlink()
    con = duckdb.connect(str(db))
    save_tables(con, "mapped", mapped)
    save_tables(con, "unmapped", unmapped)
    for name, df in (("xw_linked", xw_link), ("xw_oracle", xw_oracle), ("link_pairs", pairs)):  # noqa: B007
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df")
    con.close()

    audit_df = audit.df()
    ok, msg = audit.verify(audit_df)
    write_csv(outputs_dir / "audit_log.csv", audit_df)
    summary = {
        "as_of": DATA_AS_OF.isoformat(),
        "flow_a": {
            "nodes": sorted(received),
            "resources_received": {
                n: {t: len(v) for t, v in sorted(d.items())} for n, d in sorted(received.items())
            },
            "filter": manifest["extension"]["nodes"],
        },
        "normalization_mapped": mapped.stats,
        "normalization_unmapped": unmapped.stats,
        "dedup": dedup,
        "flow_b": {"status": flow_b_result["status"], "summary": flow_b_result["summary"]},
        "denials": [
            {
                "slug": d["slug"],
                "status": d["status"],
                "reason": d["response"].get("issue", [{}])[0].get("diagnostics"),
            }
            for d in denials
        ],
        "audit": {"entries": int(len(audit_df)), "chain_verified": ok, "detail": msg},
    }
    write_json(outputs_dir / "exchange_summary.json", summary)
    if examples_dir is not None:
        write_examples(
            examples_dir,
            raw_dir,
            broker,
            transcript_a,
            manifest,
            received,
            flow_b_result,
            b_truth,
            denials,
            audit_df,
        )
    audit.close()
    return summary


# ---------------------------------------------------------------------------------------------
# Examples (small, human-readable artifacts committed to the repo)
# ---------------------------------------------------------------------------------------------
def write_examples(
    ex: Path,
    raw_dir: Path,
    broker: Broker,
    transcript_a: dict,
    manifest: dict,
    received: dict,
    flow_b_result: dict,
    b_truth: dict,
    denials: list[dict],
    audit_df: pd.DataFrame,
) -> None:
    if ex.exists():
        shutil.rmtree(ex)
    a = ex / "01_public_health_bulk_export"
    write_json(a / "request_envelope.json", transcript_a["request"])
    (a / "kickoff_response.http").parent.mkdir(parents=True, exist_ok=True)
    (a / "kickoff_response.http").write_text(
        f"# {SYNTHETIC_LABEL}\nHTTP/1.1 202 Accepted\nContent-Location: {transcript_a['kickoff']['Content-Location']}\n",
        encoding="utf-8",
    )
    write_json(a / "complete_status_manifest.json", manifest)

    # Same person, before vs. after the minimum-necessary filter (rhc: local codes, split BP)
    lk = b_truth["links"]
    person_rows = lk.to_dict("records")
    for rec in person_rows:
        node, pid = rec["org_id"], rec["patient_id"]
        src = {
            t: [
                r
                for r in parse_ndjson((raw_dir / node / f"{t}.ndjson").read_text())
                if r["id"] == pid or r.get("subject", {}).get("reference") == f"Patient/{pid}"
            ]
            for t in PH_RESOURCE_TYPES
        }
        pseudo = ph_pseudonym("lkdph", node, pid)
        got = {
            t: [
                r
                for r in received.get(node, {}).get(t, [])
                if r["id"] == pseudo or r.get("subject", {}).get("reference") == f"Patient/{pseudo}"
            ]
            for t in PH_RESOURCE_TYPES
        }
        for t in PH_RESOURCE_TYPES:
            write_ndjson(a / "same_person_source_vs_received" / node / f"source_{t}.ndjson", src[t])
            write_ndjson(a / "same_person_source_vs_received" / node / f"received_{t}.ndjson", got[t])
    # A few received NDJSON lines per node/type for quick inspection
    for node in sorted(received):
        for t in PH_RESOURCE_TYPES:
            rows = sorted(received[node].get(t, []), key=lambda r: r["id"])[:3]
            write_ndjson(a / "received_ndjson_sample" / node / f"{t}.ndjson", rows)

    b = ex / "02_treatment_patient_query"
    write_json(b / "request_envelope.json", flow_b_result["request"])
    bundle = flow_b_result["bundle"]
    write_json(b / "response_bundle.json", bundle)
    write_json(b / "node_summary.json", {"nodes": flow_b_result["summary"]})
    write_comparison(b / "purpose_comparison.md", bundle, received, person_rows)

    c = ex / "03_refused_requests"
    for d in denials:
        write_json(
            c / f"{d['slug']}.json",
            {
                "description": d["description"],
                "endpoint": d["endpoint"],
                "request": d["request"],
                "http_status": d["status"],
                "response": d["response"],
            },
        )
    write_csv(
        ex / "audit_log_excerpt.csv",
        audit_df[
            audit_df["request_id"].isin(
                ["req-0001-ph-bulk", "req-0002-treatment-query", "req-0101-deny", "req-0104-deny"]
            )
        ],
    )


def write_comparison(path: Path, bundle: dict, received: dict, person_rows: list[dict]) -> None:
    tre = [e["resource"] for e in bundle["entry"]]
    ph = []
    for rec in person_rows:
        pseudo = ph_pseudonym("lkdph", rec["org_id"], rec["patient_id"])
        for t in PH_RESOURCE_TYPES:
            ph += [
                r
                for r in received.get(rec["org_id"], {}).get(t, [])
                if r["id"] == pseudo or r.get("subject", {}).get("reference") == f"Patient/{pseudo}"
            ]

    def count(rs, t):
        return sum(1 for r in rs if r["resourceType"] == t)

    tp = next(r for r in tre if r["resourceType"] == "Patient")
    pp = next(r for r in ph if r["resourceType"] == "Patient")
    lines = [
        f"<!-- {SYNTHETIC_LABEL} -->",
        "# Same person, two exchange purposes",
        "",
        f"> {SYNTHETIC_LABEL} Generated by `make exchange`.",
        "",
        "| Element | Treatment (T-TREAT) patient query | Public Health (T-PH) bulk export |",
        "|---|---|---|",
        f"| Patient name | `{tp['name'][0].get('given', [''])[0]} {tp['name'][0].get('family', '')}` | masked (data-absent-reason) |",
        f"| Identifier | MRN `{tp['identifier'][0]['value']}` | pseudonym `{pp['identifier'][0]['value']}` |",
        f"| Telecom | {'present' if tp.get('telecom') else 'absent'} | removed |",
        f"| Street address | `{tp['address'][0].get('line', [''])[0]}` | removed (city/county/state/ZIP kept) |",
        f"| Birth date | `{tp.get('birthDate')}` | `{pp.get('birthDate')}` (dates allowed in a limited data set) |",
        f"| PPRL linkage tokens | none | {'present' if any('pprl' in e.get('url', '') for e in pp.get('extension', [])) else 'absent'} |",
    ]
    for t in ("Condition", "Observation", "MedicationRequest", "Encounter"):
        lines.append(
            f"| {t} resources | {count(tre, t)} (all, full history) | {count(ph, t)} (value-set and date-range filtered) |"
        )
    lines += [
        "",
        "Why they differ: HIPAA's minimum-necessary standard does not apply to disclosures to a "
        "health care provider for treatment (45 CFR 164.502(b)(2)(i)), while public health disclosures "
        "(45 CFR 164.512(b)) are subject to it, and a limited data set (45 CFR 164.514(e)) excludes direct "
        "identifiers. See docs/policy_context.md. Not legal advice.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run exchange flows")
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--outputs", type=Path, default=OUTPUTS_DIR)
    ap.add_argument("--examples", type=Path, default=EXAMPLES_DIR)
    a = ap.parse_args()
    s = run(a.data / "raw", a.data / "ground_truth", a.data / "exchange", a.outputs, a.examples)
    d = s["dedup"]
    print(
        f"Flow A: received {sum(sum(v.values()) for v in s['flow_a']['resources_received'].values())} resources "
        f"from {len(s['flow_a']['nodes'])} nodes; dedup precision={d['precision']} recall={d['recall']} "
        f"({d['records']} records -> {d['predicted_persons']} persons; truth {d['true_persons']})"
    )
    print(f"Flow B: status {s['flow_b']['status']}; {s['flow_b']['summary']}")
    print(f"Refused requests: {[(x['slug'], x['status']) for x in s['denials']]}")
    print(f"Audit: {s['audit']['entries']} entries; chain verified={s['audit']['chain_verified']}")


if __name__ == "__main__":
    main()

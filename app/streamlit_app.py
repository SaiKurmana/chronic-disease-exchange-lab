"""Chronic Disease Data Exchange Lab — Streamlit app (runs offline from committed outputs/).

    streamlit run app/streamlit_app.py

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from labcore import charts  # noqa: E402
from labcore.config import (  # noqa: E402
    AUTHOR,
    DATA_AS_OF,
    DISCLAIMER,
    MP_END,
    NOT_LEGAL_ADVICE,
    OUTPUTS_DIR,
    REPO_URL,
    SYNTHETIC_LABEL,
)
from labcore.io import read_csv, read_json, read_ndjson  # noqa: E402
from network.audit import AuditLog, verify_frame  # noqa: E402
from network.broker import Broker, Envelope, ph_pseudonym  # noqa: E402
from network.policy import PH_RESOURCE_TYPES, XP_CODES  # noqa: E402

DEMO = OUTPUTS_DIR / "demo_network"

st.set_page_config(page_title="Chronic Disease Data Exchange Lab", page_icon="🩺", layout="wide")


@st.cache_data
def load():
    return {
        "directory": read_json(OUTPUTS_DIR / "network_directory.json"),
        "summary": read_json(OUTPUTS_DIR / "measures_summary.json"),
        "exchange": read_json(OUTPUTS_DIR / "exchange_summary.json"),
        "effects": read_csv(OUTPUTS_DIR / "pipeline_effects.csv"),
        "strat": read_csv(OUTPUTS_DIR / "measures_by_stratum.csv"),
        "svn": read_csv(OUTPUTS_DIR / "single_vs_network.csv"),
        "dq": read_csv(OUTPUTS_DIR / "data_quality_by_node.csv"),
        "audit": read_csv(OUTPUTS_DIR / "audit_log.csv", dtype={"detail": str}),
    }


D = load()
mode = "dark" if (st.get_option("theme.base") == "dark") else "light"

with st.sidebar:
    st.markdown("### Chronic Disease Data Exchange Lab")
    st.warning(f"**{SYNTHETIC_LABEL}**")
    page = st.radio("View", ["Network", "Send a request", "Measures", "Data quality", "Audit log", "About"])
    st.caption(DISCLAIMER)
    st.caption(f"{NOT_LEGAL_ADVICE}  \nAuthor: {AUTHOR}  \n[Source code]({REPO_URL})")

st.info(
    f"🧪 {SYNTHETIC_LABEL} Data as of {DATA_AS_OF.isoformat()} · measurement period ends {MP_END.isoformat()}."
)


def pct(x):
    return "n/a" if x is None or pd.isna(x) else f"{100 * x:.1f}%"


# ------------------------------------------------------------------------------------------------
if page == "Network":
    st.title("Simulated network")
    st.write(
        "A public health agency (PHA) and a clinician request data through a simulated network broker "
        "from five fictional healthcare organizations. The broker checks the declared TEFCA-style exchange "
        "purpose, applies a minimum-necessary filter for Public Health, and audits every step."
    )
    st.plotly_chart(charts.network_diagram(D["directory"], mode), width="stretch")
    nodes = pd.DataFrame(
        [
            {
                "Node": n["id"].upper(),
                "Organization": n["name"],
                "Type": n["kind"],
                "County": n["county"],
                "EHR flavor": n["ehr_flavor"],
                "Resources visible": sum(n["resources_visible"].values()),
                "Not yet loaded at extract": sum(n["resources_pending_as_of"].values()),
            }
            for n in D["directory"]["nodes"]
        ]
    )
    st.dataframe(nodes, hide_index=True, width="stretch")

# ------------------------------------------------------------------------------------------------
elif page == "Send a request":
    st.title("Send a request")
    st.write(
        "Build a request envelope and send it through the broker against a small committed slice of the "
        "synthetic network. Compare what each purpose returns and what is withheld."
    )
    c1, c2, c3 = st.columns(3)
    requesters = {
        "lkdph": "Health department (PHA)",
        "amc-clinician": "Clinician (Health Care Provider)",
        "acme-health-plan": "Health plan",
    }
    who = c1.selectbox("Requester", list(requesters), format_func=requesters.get)
    purpose = c2.selectbox(
        "Exchange purpose (XP code)",
        list(XP_CODES),
        index=list(XP_CODES).index("T-PH" if who != "amc-clinician" else "T-TREAT"),
        format_func=lambda k: f"{k} — {XP_CODES[k]}",
    )
    op = c3.selectbox("Operation", ["bulk-export", "patient-query"], index=0 if purpose != "T-TREAT" else 1)
    c4, c5, c6 = st.columns(3)
    start = c4.date_input("Date range start", value=pd.Timestamp("2024-01-01"))
    end = c5.date_input("Date range end", value=pd.Timestamp("2025-12-31"))
    juris = c6.text_input("Jurisdiction (PHA)", value="Lakeland State")
    types = st.multiselect(
        "Resource types", PH_RESOURCE_TYPES + ["DocumentReference"], default=PH_RESOURCE_TYPES
    )
    demo_pats = read_ndjson(DEMO / "amc" / "Patient.ndjson")
    patient = {}
    if op == "patient-query":
        opts = {
            p["id"]: f"{p['name'][0]['given'][0]} {p['name'][0]['family']} ({p['birthDate']})"
            for p in demo_pats
        }
        pid = st.selectbox(
            "Patient to look up (demographics from the clinician's own record)",
            list(opts),
            format_func=opts.get,
        )
        p = next(x for x in demo_pats if x["id"] == pid)
        patient = {
            "family": p["name"][0]["family"],
            "given": p["name"][0]["given"][0],
            "birthdate": p["birthDate"],
        }
    creds = {
        "lkdph": "demo-credential-lkdph",
        "amc-clinician": "demo-credential-amc",
        "acme-health-plan": "demo-credential-plan",
    }
    env = Envelope(
        request_id="app-req-0001",
        requester_id=who,
        credential=creds[who],
        purpose=purpose,
        operation=op,
        jurisdiction=juris or None,
        date_start=str(start) if start else None,
        date_end=str(end) if end else None,
        types=types,
        patient=patient,
    )
    with st.expander("Request envelope (JSON)"):
        st.code(json.dumps(env.to_json(), indent=2), language="json")
    if st.button("Send request", type="primary"):
        broker = Broker(DEMO, audit=AuditLog())
        if op == "bulk-export":
            status, body = broker.bulk_export(env)
        else:
            status, body = broker.patient_query(env)
        st.subheader(f"HTTP {status}")
        if status >= 400:
            st.error(body["issue"][0]["diagnostics"])
            st.code(json.dumps(body, indent=2), language="json")
        elif op == "bulk-export":
            job = body["job"]
            _, manifest = broker.bulk_status(job)
            rows = [
                {
                    "Node": n["node"].upper(),
                    "Returned": n["returned"],
                    "Withheld": sum(n["withheld"].values()),
                    "Withheld because": ", ".join(f"{k}: {v}" for k, v in n["withheld"].items()),
                }
                for n in manifest["extension"]["nodes"]
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            src = read_ndjson(DEMO / "amc" / "Patient.ndjson")[0]
            got = next(
                r
                for r in broker.outbox[job]["files"][("amc", "Patient")]
                if r["id"] == ph_pseudonym(who, "amc", src["id"])
            )
            a, b = st.columns(2)
            a.markdown("**Source Patient (inside the organization)**")
            a.json(src, expanded=False)
            b.markdown("**What Public Health receives (limited data set + PPRL tokens)**")
            b.json(got, expanded=False)
            with st.expander("Complete-status manifest"):
                st.json(manifest, expanded=False)
        else:
            st.dataframe(pd.DataFrame(body["summary"]), hide_index=True, width="stretch")
            st.markdown("**Treatment returns the full record, including identifiers:**")
            st.json(body["bundle"]["entry"][0]["resource"] if body["bundle"]["entry"] else {}, expanded=False)
        st.markdown("**Audit entries for this request**")
        st.dataframe(
            broker.audit.df()[
                [
                    "seq",
                    "event_type",
                    "target_node",
                    "outcome",
                    "http_status",
                    "records_returned",
                    "records_withheld",
                    "detail",
                ]
            ],
            hide_index=True,
            width="stretch",
        )

# ------------------------------------------------------------------------------------------------
elif page == "Measures":
    st.title("Measures dashboard")
    s = D["summary"]
    h = s["headline"]
    cols = st.columns(4)
    for col, k in zip(cols, ["htn_prevalence", "dm_prevalence", "cbp", "gsd_gt9"], strict=True):
        col.metric(
            charts.MEASURE_SHORT[k], pct(h[k]["rate"]), help=f"{h[k]['numerator']}/{h[k]['denominator']}"
        )
    st.caption(
        f"Network view, full pipeline · {s['population']['adults']} adults with a qualifying visit in "
        f"{s['measurement_period']['start'][:4]}. CBP adapted from CMS165v13; HbA1c adapted from CMS122v13 "
        "(inverse: lower is better). * = small cell (numerator < 11 or denominator < 30)."
    )
    c1, c2 = st.columns(2)
    measure = c1.selectbox("Measure", list(charts.MEASURE_SHORT), format_func=charts.MEASURE_SHORT.get)
    strat = c2.selectbox("Stratify by", ["Organization", "Age group", "Sex", "County", "Rurality"])
    st.plotly_chart(charts.stratified(D["strat"], measure, strat, mode), width="stretch")
    st.subheader("What exchange adds: single organization vs network")
    st.plotly_chart(charts.single_vs_network(D["svn"], measure, mode), width="stretch")
    st.dataframe(D["svn"], hide_index=True, width="stretch")
    st.subheader("Effect of code mapping and deduplication")
    st.plotly_chart(charts.pipeline_effects(D["effects"], mode), width="stretch")
    st.dataframe(D["effects"], hide_index=True, width="stretch")
    dd = D["exchange"]["dedup"]
    st.caption(
        f"Deduplication vs ground truth: precision {dd['precision']}, recall {dd['recall']} "
        f"({dd['records']} records → {dd['predicted_persons']} linked persons; truth {dd['true_persons']})."
    )

# ------------------------------------------------------------------------------------------------
elif page == "Data quality":
    st.title("Data quality by node")
    labels = D["summary"]["dq_metric_labels"]
    st.plotly_chart(charts.dq_heatmap(D["dq"], labels, mode), width="stretch")
    t = D["dq"].set_index("node").T
    t.index = [labels.get(i, i) for i in t.index]
    st.dataframe(t, width="stretch")

# ------------------------------------------------------------------------------------------------
elif page == "Audit log":
    st.title("Audit log")
    a = D["audit"]
    ok, msg = verify_frame(a)
    (st.success if ok else st.error)(f"Hash chain: {msg}")
    c1, c2, c3 = st.columns(3)
    rid = c1.multiselect("Request", sorted(a["request_id"].unique()))
    pur = c2.multiselect("Purpose", sorted(a["purpose_code"].dropna().unique()))
    out = c3.multiselect("Outcome", sorted(a["outcome"].dropna().unique()))
    mask = pd.Series(True, index=a.index)
    for col, sel in (("request_id", rid), ("purpose_code", pur), ("outcome", out)):
        if sel:
            mask &= a[col].isin(sel)
    f = a[mask]
    st.dataframe(f.drop(columns=["prev_hash"]), hide_index=True, width="stretch")

# ------------------------------------------------------------------------------------------------
else:
    st.title("About")
    st.markdown(
        f"""
**Chronic Disease Data Exchange Lab** is a portfolio project demonstrating a chronic disease use case for
nationwide health information exchange, inspired by TEFCA's Public Health exchange purpose.

- {DISCLAIMER}
- {SYNTHETIC_LABEL}
- {NOT_LEGAL_ADVICE}

Documentation: use case, stakeholder needs, data sharing protocol, policy context, architecture and
limitations are in the repository's `docs/` folder. Author: {AUTHOR}.
"""
    )

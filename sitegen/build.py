"""`make site`: build the static GitHub Pages site into _site/ from committed outputs/, docs/ and examples/.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.offline import get_plotlyjs_version

from labcore import charts
from labcore.config import (
    APP_URL,
    AUTHOR,
    DATA_AS_OF,
    DISCLAIMER,
    DOCS_DIR,
    EXAMPLES_DIR,
    NOT_LEGAL_ADVICE,
    OUTPUTS_DIR,
    REPO_URL,
    SITE_DIR,
    SYNTHETIC_LABEL,
)
from labcore.io import read_csv, read_json

HERE = Path(__file__).parent
DOC_ORDER = [
    "use_case",
    "stakeholder_needs",
    "data_sharing_protocol",
    "policy_context",
    "architecture",
    "limitations",
    "references",
]


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=select_autoescape(["html"]))


def _common(root: str, title: str) -> dict:
    return {
        "root": root,
        "title": title,
        "synthetic": SYNTHETIC_LABEL,
        "disclaimer": DISCLAIMER,
        "not_legal": NOT_LEGAL_ADVICE,
        "author": AUTHOR,
        "repo": REPO_URL,
        "app_url": APP_URL,
        "as_of": DATA_AS_OF.isoformat(),
    }


def _md_to_html(text: str) -> str:
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = re.sub(
        r'href="([^"#:]+)\.md(#[^"]*)?"', lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', body
    )
    return body


def _fig_pair(builder, *args) -> dict:
    return {m: json.loads(builder(*args, mode=m).to_json()) for m in ("light", "dark")}


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * float(x):.1f}%"


def build(
    out: Path = SITE_DIR, outputs: Path = OUTPUTS_DIR, docs: Path = DOCS_DIR, examples: Path = EXAMPLES_DIR
) -> Path:
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    shutil.copy(HERE / "static" / "style.css", out / "static" / "style.css")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    env = _env()

    summary = read_json(outputs / "measures_summary.json")
    exch = read_json(outputs / "exchange_summary.json")
    directory = read_json(outputs / "network_directory.json")
    effects = read_csv(outputs / "pipeline_effects.csv")
    strat = read_csv(outputs / "measures_by_stratum.csv")
    svn = read_csv(outputs / "single_vs_network.csv")
    dq = read_csv(outputs / "data_quality_by_node.csv")

    h = summary["headline"]
    stats = [
        {
            "label": charts.MEASURE_SHORT[k],
            "value": _pct(h[k]["rate"]),
            "sub": f"{h[k]['numerator']:,} / {h[k]['denominator']:,}",
        }
        for k in h
    ]
    d = exch["dedup"]
    stats.append(
        {
            "label": "Dedup precision / recall",
            "value": f"{d['precision']:.3f} / {d['recall']:.3f}",
            "sub": f"{d['records']:,} records → {d['predicted_persons']:,} persons (truth {d['true_persons']:,})",
        }
    )
    e = effects.set_index("view")
    effect_bullets = [
        f"As received, hypertension prevalence is {_pct(e.loc['network_as_received', 'htn_prevalence_rate'])}. "
        f"Mapping local codes raises it to {_pct(e.loc['network_mapped', 'htn_prevalence_rate'])}, and deduplication "
        f"(one person, one count) to {_pct(e.loc['network_linked', 'htn_prevalence_rate'])}. The latent "
        f"ground-truth prevalence is {_pct(e.loc['ground_truth', 'htn_prevalence_rate'])}; the gap is undiagnosed disease.",
        f"BP control rises from {_pct(e.loc['network_as_received', 'cbp_rate'])} as received to "
        f"{_pct(e.loc['network_linked', 'cbp_rate'])} after unit normalization and mapping. Without mapping, "
        'readings in non-UCUM units ("mmHg") and local problem codes are lost.',
        f"Without deduplication, {int(e.loc['network_mapped', 'persons']):,} patient records look like distinct people; "
        f"PPRL linkage resolves them to {int(e.loc['network_linked', 'persons']):,} "
        f"(ground truth {int(e.loc['network_oracle', 'persons']):,}).",
    ]
    svn_bullets = [
        f"{r.org.upper()}: {r.pct_with_records_at_other_orgs:.0f}% of adult patients have records elsewhere; "
        f"for {r.pct_latest_bp_from_other_org:.0f}% of its BP-control denominator, the most recent BP came from another organization."
        for r in svn.itertuples()
    ]
    labels = summary["dq_metric_labels"]
    dqi = dq.set_index("node")
    dq_bullets = [
        f"RHC: only {dqi.loc['rhc', 'dx_standard_code_pct']:.0f}% of chronic diagnoses use standard codes "
        f"(local codes mapped by the PHA); median availability lag {dqi.loc['rhc', 'median_lag_days']:.0f} days "
        f"(monthly batches), and {int(dqi.loc['rhc', 'pending_at_extract'])} records were not yet loaded at the extract date.",
        f"IPP: {dqi.loc['ipp', 'bp_ucum_pct']:.0f}% of BP values use UCUM units and {dqi.loc['ipp', 'med_rxnorm_pct']:.0f}% of "
        f"medications have RxNorm codes; {dqi.loc['ipp', 'us_core_conformant_pct']:.0f}% of profiled resources meet US Core "
        "'must have' rules.",
        f"FQHC: {dqi.loc['fqhc', 'a1c_loinc_pct']:.0f}% of HbA1c results carry LOINC (the rest are IFCC point-of-care, "
        f"converted to NGSP %). MMG: {int(dqi.loc['mmg', 'duplicate_bp_resends'])} duplicate BP resends removed.",
        "All exchanged resources pass FHIR structural validation.",
    ]
    table = [
        {
            "label": summary["measure_labels"][k],
            "num": f"{h[k]['numerator']:,}",
            "den": f"{h[k]['denominator']:,}",
            "rate": _pct(h[k]["rate"]),
        }
        for k in h
    ]
    chart_specs = {
        "chart-effects": _fig_pair(charts.pipeline_effects, effects),
        "chart-svn": _fig_pair(charts.single_vs_network, svn, "cbp"),
        "chart-county": _fig_pair(charts.stratified, strat, "cbp", "County"),
        "chart-dq": _fig_pair(charts.dq_heatmap, dq, labels),
    }
    docs_list = []
    for slug in DOC_ORDER:
        text = (docs / f"{slug}.md").read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        docs_list.append({"slug": slug, "title": title, "text": text})

    ctx = _common("", "Home") | {
        "nodes": directory["nodes"],
        "denials": exch["denials"],
        "stats": stats,
        "population": f"{summary['population']['adults']:,}",
        "effect_bullets": effect_bullets,
        "svn_bullets": svn_bullets,
        "dq_bullets": dq_bullets,
        "table": table,
        "docs": docs_list,
        "charts_json": json.dumps(chart_specs).replace("</", "<\\/"),
        "plotly_js": get_plotlyjs_version(),
    }
    (out / "index.html").write_text(env.get_template("index.html").render(**ctx), encoding="utf-8")

    # Docs
    (out / "docs").mkdir()
    shutil.copytree(docs / "diagrams", out / "docs" / "diagrams")
    doc_tpl = env.get_template("doc.html")
    for dd in docs_list:
        page = doc_tpl.render(**_common("../", dd["title"]), body=_md_to_html(dd["text"]))
        (out / "docs" / f"{dd['slug']}.html").write_text(page, encoding="utf-8")
    idx = (
        "# Documentation\n\n> "
        + SYNTHETIC_LABEL
        + "\n\n"
        + "\n".join(f"- [{dd['title']}]({dd['slug']}.md)" for dd in docs_list)
    )
    (out / "docs" / "index.html").write_text(
        doc_tpl.render(**_common("../", "Documentation"), body=_md_to_html(idx)), encoding="utf-8"
    )

    # Examples: copy raw files; render Markdown; build an index page
    shutil.copytree(examples, out / "examples")
    for md in (out / "examples").rglob("*.md"):
        rel_root = "../" * (len(md.relative_to(out).parts) - 1)
        md.with_suffix(".html").write_text(
            doc_tpl.render(**_common(rel_root, md.stem), body=_md_to_html(md.read_text(encoding="utf-8"))),
            encoding="utf-8",
        )
    files = sorted(
        p.relative_to(out / "examples").as_posix()
        for p in (out / "examples").rglob("*")
        if p.is_file() and p.suffix != ".md"
    )
    items = "\n".join(f'<li><a href="{html.escape(f)}">{html.escape(f)}</a></li>' for f in files)
    body = (
        f"<h1>Examples</h1><blockquote>{SYNTHETIC_LABEL} Generated by <code>make exchange</code>.</blockquote>"
        "<p>Request envelopes, Bulk Data manifests, NDJSON before/after the minimum-necessary filter, a Treatment "
        "response, refused requests (OperationOutcome) and audit entries.</p>"
        f"<ul class='small'>{items}</ul>"
    )
    (out / "examples" / "index.html").write_text(
        doc_tpl.render(**_common("../", "Examples"), body=body), encoding="utf-8"
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=SITE_DIR)
    a = ap.parse_args()
    out = build(a.out)
    n = sum(1 for _ in out.rglob("*.html"))
    print(f"Site built: {n} HTML pages in {out}")


if __name__ == "__main__":
    main()

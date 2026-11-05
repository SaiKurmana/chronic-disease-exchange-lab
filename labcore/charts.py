"""Plotly figure builders shared by the Streamlit app and the static site.

Palette: categorical slots 1-3 (blue, orange, aqua) of the validated reference palette in the
order they are defined; sequential blue ramp for heatmaps. Every figure carries the
synthetic-data label.

Synthetic data — for demonstration only.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from .config import SYNTHETIC_LABEL

SERIES = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
}
SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
INK = {"light": ("#0b0b0b", "#52514e", "#e6e5e1"), "dark": ("#f0efec", "#c3c2b7", "#33322f")}
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

VIEW_LABELS = {
    "network_as_received": "As received",
    "network_mapped": "+ code mapping",
    "network_linked": "+ deduplication",
    "network_oracle": "Perfect linkage",
    "ground_truth": "Ground truth (latent)",
}
MEASURE_SHORT = {
    "htn_prevalence": "Hypertension prevalence",
    "dm_prevalence": "Diabetes prevalence",
    "cbp": "BP controlled <140/90",
    "gsd_gt9": "HbA1c >9% or missing",
}


def _layout(fig: go.Figure, title: str, mode: str = "light", height: int = 380) -> go.Figure:
    ink, ink2, grid = INK[mode]
    fig.update_layout(
        title={
            "text": f"{title}<br><sup>{SYNTHETIC_LABEL}</sup>",
            "x": 0,
            "xanchor": "left",
            "font": {"size": 16, "color": ink},
        },
        paper_bgcolor=SURFACE[mode],
        plot_bgcolor=SURFACE[mode],
        height=height,
        font={"family": "Inter, system-ui, -apple-system, Segoe UI, sans-serif", "color": ink2, "size": 12},
        margin={"l": 10, "r": 10, "t": 70, "b": 10},
        bargap=0.35,
        bargroupgap=0.08,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "xanchor": "right",
            "x": 1,
            "font": {"color": ink2},
        },
        hoverlabel={"bgcolor": SURFACE[mode], "font": {"color": ink}},
    )
    fig.update_xaxes(gridcolor=grid, zeroline=False, linecolor=grid, automargin=True)
    fig.update_yaxes(gridcolor=grid, zeroline=False, linecolor=grid, automargin=True)
    fig.update_traces(selector={"type": "bar"}, marker_line_width=0)
    return fig


def pipeline_effects(effects: pd.DataFrame, mode: str = "light") -> go.Figure:
    """Grouped bars: each pipeline step (x) x two measures; shows what mapping & dedup change."""
    e = effects.set_index("view")
    views = [v for v in VIEW_LABELS if v in e.index]
    fig = go.Figure()
    for i, m in enumerate(["htn_prevalence", "cbp"]):
        ys = [e.loc[v, f"{m}_rate"] * 100 if pd.notna(e.loc[v, f"{m}_rate"]) else None for v in views]
        fig.add_bar(
            name=MEASURE_SHORT[m],
            x=[VIEW_LABELS[v] for v in views],
            y=ys,
            marker_color=SERIES[mode][i],
            text=[f"{y:.1f}%" if y is not None else "n/a" for y in ys],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}<br>" + MEASURE_SHORT[m] + ": %{y:.1f}%<extra></extra>",
        )
    fig.update_yaxes(title="Percent", ticksuffix="%", rangemode="tozero")
    return _layout(fig, "How code mapping and deduplication change the numbers", mode)


def stratified(strat: pd.DataFrame, measure: str, stratifier: str, mode: str = "light") -> go.Figure:
    d = strat[(strat.measure == measure) & (strat.stratifier == stratifier)].copy()
    d["pct"] = d["rate"] * 100
    fig = go.Figure(
        go.Bar(
            x=d["pct"],
            y=d["stratum"],
            orientation="h",
            marker_color=SERIES[mode][0],
            text=[f"{p:.1f}%" + (" *" if s else "") for p, s in zip(d["pct"], d["small_cell"], strict=True)],
            textposition="outside",
            cliponaxis=False,
            customdata=d[["numerator", "denominator"]].values,
            hovertemplate="%{y}: %{x:.1f}% (%{customdata[0]}/%{customdata[1]})<extra></extra>",
        )
    )
    fig.update_xaxes(ticksuffix="%", rangemode="tozero")
    fig.update_yaxes(autorange="reversed")
    title = f"{MEASURE_SHORT[measure]} by {stratifier.lower()} (network view)"
    return _layout(fig, title, mode, height=max(260, 70 + 42 * len(d)))


def single_vs_network(svn: pd.DataFrame, measure: str, mode: str = "light") -> go.Figure:
    fig = go.Figure()
    for i, (suffix, name) in enumerate(
        [("org_only", "Single organization's own data"), ("network", "Network view (same patients)")]
    ):
        ys = svn[f"{measure}_{suffix}"] * 100
        fig.add_bar(
            name=name,
            x=svn["org"].str.upper(),
            y=ys,
            marker_color=SERIES[mode][i],
            text=[f"{y:.1f}%" for y in ys],
            textposition="outside",
            cliponaxis=False,
            customdata=svn["org_name"],
            hovertemplate="%{customdata}<br>" + name + ": %{y:.1f}%<extra></extra>",
        )
    fig.update_yaxes(ticksuffix="%", rangemode="tozero")
    return _layout(fig, f"{MEASURE_SHORT[measure]}: single organization vs network", mode)


def dq_heatmap(dq: pd.DataFrame, labels: dict, mode: str = "light") -> go.Figure:
    cols = [c for c in dq.columns if c.endswith("_pct") and dq[c].notna().any()]
    z = dq[cols].T.values
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=dq["node"].str.upper(),
            y=[labels.get(c, c) for c in cols],
            zmin=0,
            zmax=100,
            colorscale=[[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(SEQ_BLUE)],
            text=[[f"{v:.0f}" if pd.notna(v) else "" for v in row] for row in z],
            texttemplate="%{text}",
            hovertemplate="%{x} — %{y}: %{z:.1f}%<extra></extra>",
            xgap=2,
            ygap=2,
            colorbar={"title": "%", "thickness": 10},
        )
    )
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, "Data quality by node (higher is better)", mode, height=120 + 30 * len(cols))


def network_diagram(directory: dict, mode: str = "light") -> go.Figure:
    """Hub-and-spoke view: requesters -> broker -> organization nodes."""
    ink, ink2, grid = INK[mode]
    nodes = directory["nodes"]
    pos = {"broker": (0.5, 0.5), "lkdph": (0.08, 0.78), "amc-clinician": (0.08, 0.22)}
    for i, n in enumerate(nodes):
        pos[n["id"]] = (0.92, 0.9 - i * (0.8 / max(1, len(nodes) - 1)))
    fig = go.Figure()
    for k, (x, y) in pos.items():
        if k == "broker":
            continue
        fig.add_shape(
            type="line",
            x0=pos["broker"][0],
            y0=pos["broker"][1],
            x1=x,
            y1=y,
            line={"color": grid if mode == "light" else ink2, "width": 2},
        )
    groups = [
        ("Public health / clinician requesters", ["lkdph", "amc-clinician"], SERIES[mode][1]),
        ("Network broker (simulated)", ["broker"], SERIES[mode][0]),
        ("Healthcare organization nodes", [n["id"] for n in nodes], SERIES[mode][2]),
    ]
    names = {
        "broker": "Broker",
        "lkdph": "Health dept (PHA)",
        "amc-clinician": "Clinician",
        **{n["id"]: f"{n['id'].upper()}<br>{n['kind']}" for n in nodes},
    }
    hover = {
        "broker": "Authenticates, checks purpose, routes, filters, audits",
        "lkdph": "Lakeland Department of Public Health (fictional): T-PH bulk export",
        "amc-clinician": "Clinician: T-TREAT patient query",
        **{n["id"]: f"{n['name']}<br>{n['ehr_flavor']}" for n in nodes},
    }
    for label, ids, color in groups:
        fig.add_scatter(
            x=[pos[i][0] for i in ids],
            y=[pos[i][1] for i in ids],
            mode="markers+text",
            name=label,
            marker={"size": 26, "color": color, "line": {"color": SURFACE[mode], "width": 2}},
            text=[names[i] for i in ids],
            textposition="bottom center",
            textfont={"color": ink, "size": 11},
            hovertext=[hover[i] for i in ids],
            hoverinfo="text",
        )
    fig.update_xaxes(visible=False, range=[-0.05, 1.08])
    fig.update_yaxes(visible=False, range=[-0.02, 1.02])
    fig = _layout(fig, "Simulated network: requesters → broker → organizations", mode, height=480)
    fig.update_layout(legend={"orientation": "h", "yanchor": "top", "y": -0.02, "xanchor": "left", "x": 0})
    return fig

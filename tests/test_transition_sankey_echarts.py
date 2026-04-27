"""Unit tests for transition Sankey ECharts option builder."""

from __future__ import annotations

import pandas as pd

import plotly.graph_objects as go

from app.tabs.viz_charts import _filtered_transition_edges, build_transition_sankey_echarts_options


def test_build_transition_sankey_echarts_options_basic() -> None:
    edges = pd.DataFrame(
        {
            "from_stage": [1, 2, 1],
            "to_stage": [2, 3, 3],
            "n_apps": [100, 40, 25],
        }
    )
    stage_label = {
        1: "01 · A · Submitted",
        2: "02 · B · Review",
        3: "03 · C · Offer sent",
    }
    out = build_transition_sankey_echarts_options(
        edges,
        stage_label=stage_label,
        top_k=10,
        min_apps=1,
        include_self_loops=True,
        compact_node_labels=True,
    )
    assert out is not None
    options, height, mapping = out
    assert height >= 620
    assert "series" in options
    ser = options["series"][0]
    assert ser["type"] == "sankey"
    assert ser["layoutIterations"] == 0
    assert ser["emphasis"]["focus"] == "none"
    assert ser["label"]["textBorderWidth"] >= 2
    assert ser["data"][0]["depth"] == 0
    assert len(ser["links"]) >= 2
    names = {d["name"] for d in options["series"][0]["data"]}
    assert len(names) == 3
    assert mapping and set(mapping[0].keys()) == {"code", "stage", "short"}


def test_build_transition_sankey_prominent_layout() -> None:
    edges = pd.DataFrame({"from_stage": [1, 2], "to_stage": [2, 3], "n_apps": [50, 30]})
    out = build_transition_sankey_echarts_options(
        edges,
        stage_label={1: "01 · A", 2: "02 · B", 3: "03 · C"},
        top_k=10,
        min_apps=1,
        include_self_loops=True,
        compact_node_labels=False,
        prominent=True,
    )
    assert out is not None
    options, height, mapping = out
    assert height >= 780
    assert options["series"][0]["nodeWidth"] == 20
    assert "media" in options and options["media"][0]["query"]["maxWidth"] == 520
    assert len(mapping) == 3


def test_build_transition_sankey_excludes_self_loop_when_disabled() -> None:
    edges = pd.DataFrame({"from_stage": [1], "to_stage": [1], "n_apps": [99]})
    out = build_transition_sankey_echarts_options(
        edges,
        stage_label={1: "01 · Only"},
        top_k=10,
        min_apps=1,
        include_self_loops=False,
        compact_node_labels=True,
    )
    assert out is None


def test_filtered_transition_edges_top_k_orders_by_weight() -> None:
    edges = pd.DataFrame({"from_stage": [1, 2], "to_stage": [2, 3], "n_apps": [10, 100]})
    out = _filtered_transition_edges(edges, top_k=1, min_apps=1, include_self_loops=True)
    assert out is not None and len(out) == 1
    assert int(out.iloc[0]["n_apps"]) == 100


def test_plotly_sankey_trace_matches_dialog_shape() -> None:
    """Plotly Sankey used in ``st.dialog`` must accept node customdata + link arrays."""
    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(
                    pad=14,
                    thickness=16,
                    label=["01", "02"],
                    color=["#4C78A8", "#59A14F"],
                    customdata=["Stage one", "Stage two"],
                    hovertemplate="<b>%{customdata}</b><extra></extra>",
                ),
                link=dict(
                    source=[0],
                    target=[1],
                    value=[42],
                    color=["rgba(148, 163, 184, 0.42)"],
                ),
            )
        ]
    )
    assert fig.data[0].type == "sankey"

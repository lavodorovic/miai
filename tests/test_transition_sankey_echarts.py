"""Unit tests for transition Sankey ECharts option builder."""

from __future__ import annotations

import pandas as pd

from app.tabs.viz_charts import build_transition_sankey_echarts_options


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

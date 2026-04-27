"""Streamlit, Altair, and Apache ECharts chart helpers for the operations dashboard."""
from __future__ import annotations

import calendar
import html
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_echarts5 import st_echarts

from app.tabs.constants import LOOP_ACTIONS
from app.tabs.shared import stage_category_color

__all__ = [
    "_funnel_chart",
    "_swimlane_chart",
    "_who_has_ball_chart",
    "_transition_sankey",
    "build_transition_sankey_echarts_options",
    "_transition_edge_bars",
    "_transition_heatmap",
    "_history_loop_flags",
    "_truncate_cell",
    "_history_html_table",
    "_date_range_days",
    "_executive_insights",
    "_capacity_calendar_html",
    "_team_open_cases_chart",
    "_team_backlog_throughput_chart",
    "_team_workload_exceptions",
    "_bottleneck_score_chart",
    "_bottleneck_aging_chart",
    "_rework_product_chart",
    "_overview_sla_stacked_bars",
    "_throughput_daily_chart",
    "_cohort_in_flight_line",
    "_cohort_survival_lines",
    "_cohort_time_to_offer_bars",
    "_cohort_stage_heatmap",
    "_cohort_multi_trajectory_charts",
    "_period_start_end_grouped_bars",
    "_period_arrivals_losses_by_day",
    "_team_closures_heatmap",
    "_rework_interaction_dist_chart",
    "_investigator_staged_gantt",
    "_capacity_fte_sweep_chart",
    "_bottleneck_inflow_outflow_chart",
    "_period_net_stage_delta_chart",
    "_rework_outcome_offer_rate_chart",
    "_team_actor_outcome_chart",
    "_capacity_scenario_bars",
    "_sla_weekly_heatmap",
    "_investigator_dwell_with_cohort_median",
]


def _funnel_chart(funnel_df: pd.DataFrame) -> None:
    """Horizontal bars = count of apps whose *latest* audit row maps to that stage (not flow arrows)."""
    # When only a few buckets are non-zero (common in demos), a fixed tall chart makes bars
    # visually merge into a single block. Scale height to the number of rows shown.
    n_rows = int(len(funnel_df))
    height = max(140, min(720, n_rows * 34))
    chart = (
        alt.Chart(funnel_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "active_applications:Q",
                title="Applications (each counted once — latest status only)",
            ),
            y=alt.Y(
                "step_label:N",
                sort=alt.EncodingSortField(field="step_order", order="ascending"),
                title="Process stage (ordered like your state machine)",
            ),
            tooltip=[
                "step_label",
                "step_order",
                "active_applications",
                alt.Tooltip("avg_days_in_stage:Q", format=".2f", title="Avg days in stage"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def _swimlane_chart(swimlane_df: pd.DataFrame) -> None:
    n_rows = int(len(swimlane_df))
    height = max(140, min(520, n_rows * 42))
    nrows = int(len(swimlane_df))
    pal = stage_category_color() * max(1, (nrows + 7) // 8)
    chart = (
        alt.Chart(swimlane_df)
        .mark_bar()
        .encode(
            x=alt.X(
                "active_applications:Q",
                title="Applications (each counted once — latest status only)",
            ),
            y=alt.Y(
                "swimlane_label:N",
                sort=alt.EncodingSortField(field="swimlane_order", order="ascending"),
                title="Process swimlane",
            ),
            color=alt.Color("swimlane_label:N", scale=alt.Scale(range=pal[:nrows])),
            tooltip=[
                "swimlane_label",
                "active_applications",
                alt.Tooltip("avg_days_in_stage:Q", format=".2f", title="Avg days since last event"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def _who_has_ball_chart(df: pd.DataFrame) -> None:
    chart = (
        alt.Chart(df)
        .mark_arc(innerRadius=55)
        .encode(
            theta=alt.Theta("n_applications:Q"),
            color=alt.Color("team:N", legend=alt.Legend(title="Team")),
            tooltip=[
                "team",
                "n_applications",
                alt.Tooltip("pct_of_inflight:Q", format=".1f", title="% of in-flight"),
            ],
        )
        .properties(height=240)
    )
    st.altair_chart(chart, width="stretch")


def _compact_transition_stage_label(s: str, *, max_len: int) -> str:
    parts = [p.strip() for p in s.split("·")]
    if len(parts) >= 2:
        step = parts[0].split()[0].strip()
        bucket = (
            parts[1]
            .replace("DOCUMENTS_UPLOAD", "Docs")
            .replace("SUBMITTED", "Submitted")
            .replace("INITIAL", "Initial")
            .replace("REVIEW", "Review")
            .replace("INTERACTION_SUMMARY", "RFI")
            .replace("INTERACTION_SUBMITTED", "RFI reply")
            .replace("OFFER_RESPONSE", "Offer response")
            .replace("OFFER_SENT", "Offer sent")
            .replace("Post-accept", "Post accept")
            .strip()
        )
        out = f"{step} {bucket}"
    else:
        out = s.strip()
    if len(out) > max_len:
        return out[: max_len - 1] + "…"
    return out


def build_transition_sankey_echarts_options(
    edges: pd.DataFrame,
    *,
    stage_label: dict[int, str],
    top_k: int,
    min_apps: int,
    include_self_loops: bool,
    compact_node_labels: bool,
    prominent: bool = False,
) -> tuple[dict[str, Any], int, list[dict[str, str]]] | None:
    """
    Build Apache ECharts option dict for a stage-to-stage Sankey.

    Input edges must have columns: from_stage, to_stage, n_apps (unique apps per edge).

    Returns (options, height_px, stage_code_mapping) or None if no drawable graph.
    """
    if edges.empty:
        return None

    work = edges.copy()
    if not include_self_loops:
        work = work.loc[work["from_stage"] != work["to_stage"]].copy()
    work = work.loc[work["n_apps"] >= int(min_apps)].copy()
    if work.empty:
        return None

    work = work.sort_values("n_apps", ascending=False).head(int(top_k)).copy()

    raw_nodes = sorted({int(x) for x in set(work["from_stage"]).union(set(work["to_stage"]))})
    full_labels = [stage_label.get(int(s), f"Stage {int(s)}") for s in raw_nodes]

    if prominent:
        max_canvas = 56 if not compact_node_labels else 34
    else:
        max_canvas = 18 if compact_node_labels else 42
    short_labels = [_compact_transition_stage_label(s, max_len=max_canvas) for s in full_labels]
    # Use compact numeric node codes in-chart; show full mapping below chart.
    node_keys = [f"{int(s):02d}" for s in raw_nodes]
    stage_to_key = {int(s): node_keys[i] for i, s in enumerate(raw_nodes)}
    stage_code_mapping = [
        {"code": node_keys[i], "stage": full_labels[i], "short": short_labels[i]}
        for i in range(len(raw_nodes))
    ]

    palette = [
        "#4C78A8",
        "#59A14F",
        "#F28E2B",
        "#B07AA1",
        "#76B7B2",
        "#EDC948",
        "#E15759",
        "#9C755F",
    ]
    node_colors = [palette[i % len(palette)] for i in range(len(raw_nodes))]

    link_values = [int(v) for v in work["n_apps"].tolist()]
    max_link = max(link_values) if link_values else 1

    # Links: no per-link opacity overrides — ECharts paints ribbons after labels, so we keep
    # series-level strokes faint; hover (emphasis) brightens them.
    links: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        v = int(row["n_apps"])
        links.append(
            {
                "source": stage_to_key[int(row["from_stage"])],
                "target": stage_to_key[int(row["to_stage"])],
                "value": v,
            }
        )

    # Columns left → right follow `step_order` (raw_nodes is sorted). Explicit `depth` +
    # `layoutIterations: 0` stops ECharts from reshuffling nodes into an unreadable blob.
    data = [
        {
            "name": node_keys[i],
            "depth": i,
            "itemStyle": {
                "color": node_colors[i],
                "borderColor": "rgba(148, 163, 184, 0.85)",
                "borderWidth": 0.5,
                "opacity": 1,
            },
        }
        for i in range(len(raw_nodes))
    ]

    if prominent:
        height = int(max(780, min(1680, 520 + 52 * len(raw_nodes))))
        node_width, node_gap = 20, 18
        margin_lr = ("2%", "24%")
        label_fs = 13
        link_base_opacity = 0.09
    else:
        height = int(max(620, min(1100, 360 + 38 * len(raw_nodes))))
        node_width, node_gap = 14, 14
        margin_lr = ("2%", "18%")
        label_fs = 11
        link_base_opacity = 0.08

    # Labels are short stage codes above bars; full labels are shown in a table below.
    label_style: dict[str, Any] = {
        "show": True,
        "position": "top",
        "distance": 3,
        "fontSize": label_fs,
        "color": "#0f172a",
        "fontWeight": 600,
        "textBorderColor": "#ffffff",
        "textBorderWidth": 2,
        "backgroundColor": "rgba(255,255,255,0.96)",
        "borderColor": "rgba(148, 163, 184, 0.8)",
        "borderWidth": 1,
        "borderRadius": 5,
        "padding": [2, 6],
        "shadowBlur": 4,
        "shadowColor": "rgba(15, 23, 42, 0.18)",
    }

    series: dict[str, Any] = {
        "type": "sankey",
        "orient": "horizontal",
        "nodeAlign": "left",
        "layoutIterations": 0,
        "draggable": True,
        "nodeWidth": node_width,
        "nodeGap": node_gap,
        "left": margin_lr[0],
        "right": margin_lr[1],
        "top": "20%" if prominent else "16%",
        "bottom": "6%",
        "data": data,
        "links": links,
        "lineStyle": {
            "color": "rgba(148, 163, 184, 0.55)",
            "curveness": 0.32,
            "opacity": link_base_opacity,
        },
        "label": label_style,
        "emphasis": {
            "focus": "none",
            "label": {
                "fontSize": label_fs + 1,
                "fontWeight": 700,
                "backgroundColor": "rgba(255,255,255,1)",
                "textBorderWidth": 2,
            },
            "lineStyle": {"opacity": 0.62, "width": 1.6},
        },
    }

    options: dict[str, Any] = {
        "backgroundColor": "#ffffff",
        "title": {
            "text": "Where applications moved (in-period)",
            "subtext": "Apache ECharts Sankey · columns = step order (not Plotly)",
            "left": "center",
            "top": 4,
            "textStyle": {"fontSize": 15 if prominent else 13, "fontWeight": 600, "color": "#0f172a"},
            "subtextStyle": {"fontSize": 11, "color": "#64748b"},
        },
        "textStyle": {"fontFamily": "system-ui, -apple-system, Segoe UI, sans-serif"},
        "tooltip": {
            "trigger": "item",
            "triggerOn": "mousemove|click",
            "confine": True,
            "borderWidth": 0,
            "backgroundColor": "rgba(255,255,255,0.96)",
            "textStyle": {"color": "#1f2937"},
        },
        "toolbox": {
            "show": True,
            "right": 8,
            "top": 36,
            "itemSize": 15,
            "feature": {"saveAsImage": {"title": "PNG", "pixelRatio": 2}},
        },
        "series": [series],
    }
    if prominent:
        options["media"] = [
            {
                "query": { "maxWidth": 520 },
                "option": {
                    "title": {
                        "textStyle": {"fontSize": 13},
                        "subtextStyle": {"fontSize": 9},
                    },
                    "toolbox": {"show": False},
                    "series": [
                        {
                            "type": "sankey",
                            "nodeWidth": max(12, node_width - 4),
                            "nodeGap": max(10, node_gap - 2),
                            "top": "22%",
                            "label": {"fontSize": max(11, label_fs - 1), "padding": [2, 6], "distance": 2},
                        }
                    ],
                },
            }
        ]
    return options, height, stage_code_mapping


def _transition_sankey(
    edges: pd.DataFrame,
    *,
    stage_label: dict[int, str],
    top_k: int,
    min_apps: int,
    include_self_loops: bool,
    compact_node_labels: bool,
    prominent: bool = False,
    chart_height: str | None = None,
    chart_key: str = "transition_sankey_echarts",
) -> None:
    """
    Sankey of stage-to-stage movement (Apache ECharts via streamlit-echarts5).

    Input edges must have columns: from_stage, to_stage, n_apps (unique apps per edge).
    """
    if edges.empty:
        st.info("No stage-to-stage movement inside this window for the current cohort.")
        return

    built = build_transition_sankey_echarts_options(
        edges,
        stage_label=stage_label,
        top_k=top_k,
        min_apps=min_apps,
        include_self_loops=include_self_loops,
        compact_node_labels=compact_node_labels,
        prominent=prominent,
    )
    if built is None:
        st.info("No edges left after filters (min weight / self-loops).")
        return

    options, height, stage_map = built
    st.caption(
        "Nodes are shown as stage codes (e.g., 04, 10) to keep ribbons readable. "
        "Use the mapping table below for full stage names."
    )
    if chart_height is not None:
        h = chart_height
    elif prominent:
        h = f"min(88vh, {int(height)}px)"
    else:
        h = f"{height}px"
    st_echarts(
        options=options,
        height=h,
        width="100%",
        renderer="canvas",
        key=chart_key,
    )
    st.caption("Stage code mapping")
    st.dataframe(pd.DataFrame(stage_map), hide_index=True, width="stretch")


def _transition_edge_bars(edges: pd.DataFrame, *, top_k: int, min_apps: int, include_self_loops: bool) -> None:
    work = edges.copy()
    if not include_self_loops:
        work = work.loc[work["from_stage"] != work["to_stage"]].copy()
    work = work.loc[work["n_apps"] >= int(min_apps)].copy()
    if work.empty:
        st.info("No transitions left after filters.")
        return

    work = work.sort_values("n_apps", ascending=False).head(int(top_k)).copy()
    work["transition"] = (
        work["from_stage"].astype(int).map("{:02d}".format)
        + " -> "
        + work["to_stage"].astype(int).map("{:02d}".format)
    )
    chart = (
        alt.Chart(work)
        .mark_bar()
        .encode(
            x=alt.X("n_apps:Q", title="Applications"),
            y=alt.Y("transition:N", sort="-x", title="Transition"),
            color=alt.Color("n_apps:Q", title="Applications", legend=None),
            tooltip=[
                "from_label",
                "to_label",
                "n_apps",
            ],
        )
        .properties(height=max(260, min(620, 28 * len(work))))
    )
    st.altair_chart(chart, width="stretch")


def _transition_heatmap(edges: pd.DataFrame, *, top_k: int, min_apps: int, include_self_loops: bool) -> None:
    work = edges.copy()
    if not include_self_loops:
        work = work.loc[work["from_stage"] != work["to_stage"]].copy()
    work = work.loc[work["n_apps"] >= int(min_apps)].copy()
    if work.empty:
        st.info("No transition matrix after filters.")
        return

    from_stages = work.groupby("from_stage")["n_apps"].sum().sort_values(ascending=False).head(12).index
    to_stages = work.groupby("to_stage")["n_apps"].sum().sort_values(ascending=False).head(12).index
    work = work.loc[work["from_stage"].isin(from_stages) & work["to_stage"].isin(to_stages)].copy()
    work = work.sort_values("n_apps", ascending=False).head(int(top_k)).copy()
    work["from_step"] = work["from_stage"].astype(int).map("{:02d}".format)
    work["to_step"] = work["to_stage"].astype(int).map("{:02d}".format)
    chart = (
        alt.Chart(work)
        .mark_rect()
        .encode(
            x=alt.X("to_step:N", title="To stage"),
            y=alt.Y("from_step:N", title="From stage"),
            color=alt.Color("n_apps:Q", title="Applications"),
            tooltip=["from_label", "to_label", "n_apps"],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, width="stretch")


def _history_loop_flags(df: pd.DataFrame) -> pd.Series:
    """Boolean mask: repeat compliance / interaction actions (review loops)."""
    work = df.copy().reset_index(drop=True)
    in_loop_action = work["action"].isin(LOOP_ACTIONS)
    dup = work.groupby(["application_id", "action"], sort=False).cumcount()
    return in_loop_action & (dup > 0)


def _truncate_cell(value: object, max_len: int) -> str:
    s = str(value) if value is not None else ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _history_html_table(df: pd.DataFrame, loop_mask: pd.Series) -> str:
    """Scrollable HTML table with red rows for loop_mask (no pandas Styler dependency)."""
    rows_html: list[str] = []
    for i, row in df.reset_index(drop=True).iterrows():
        bg = "background-color:#ffcccc;" if bool(loop_mask.iloc[i]) else ""
        desc = html.escape(_truncate_cell(row.get("description", ""), 160))
        ctx = html.escape(_truncate_cell(row.get("context", ""), 320))
        rows_html.append(
            "<tr style='{bg}'>"
            "<td style='padding:6px;border-bottom:1px solid #ddd;white-space:nowrap'>{ts}</td>"
            "<td style='padding:6px;border-bottom:1px solid #ddd'>{actor}</td>"
            "<td style='padding:6px;border-bottom:1px solid #ddd;white-space:nowrap'>{action}</td>"
            "<td style='padding:6px;border-bottom:1px solid #ddd'>{desc}</td>"
            "<td style='padding:6px;border-bottom:1px solid #ddd;font-size:12px'>{ctx}</td>"
            "</tr>".format(
                bg=bg,
                ts=html.escape(str(row.get("timestamp", ""))),
                actor=html.escape(str(row.get("actor", ""))),
                action=html.escape(str(row.get("action", ""))),
                desc=desc,
                ctx=ctx,
            )
        )
    thead = (
        "<thead><tr style='text-align:left;background:#f5f5f5'>"
        "<th style='padding:6px'>When</th><th style='padding:6px'>Actor</th>"
        "<th style='padding:6px'>Action</th><th style='padding:6px'>Description</th>"
        "<th style='padding:6px'>Context</th></tr></thead>"
    )
    return (
        "<div style='overflow:auto;max-height:720px;border:1px solid #ddd;border-radius:6px'>"
        "<table style='width:100%;border-collapse:collapse;font-family:system-ui,sans-serif;font-size:13px'>"
        f"{thead}<tbody>{''.join(rows_html)}</tbody></table></div>"
    )


def _date_range_days(date_range: tuple[str, str]) -> tuple[str, str]:
    start_s, end_s = (str(date_range[0])[:10], str(date_range[1])[:10])
    return start_s, end_s


def _executive_insights(
    *,
    n_active: int,
    n_stuck: int,
    pct_stuck: float,
    thr_7d: int,
    thr_ma7: float,
    sla: pd.DataFrame,
    ball: pd.DataFrame,
) -> list[str]:
    insights: list[str] = []
    if n_active:
        insights.append(f"{n_active:,} applications are still in-flight; {n_stuck:,} are stuck over 48h ({pct_stuck:.1f}%).")
    else:
        insights.append("No in-flight applications in the current filter.")

    if not sla.empty:
        breached = sla.loc[sla["status"] == "breached"].copy()
        if not breached.empty:
            top = breached.sort_values("n_applications", ascending=False).iloc[0]
            insights.append(f"Largest SLA breach pocket: {top['sla_area']} with {int(top['n_applications']):,} applications.")
    if not ball.empty:
        top_team = ball.sort_values("n_applications", ascending=False).iloc[0]
        insights.append(f"Most in-flight work currently waits on {top_team['team']} ({int(top_team['n_applications']):,} apps).")
    insights.append(f"Terminal throughput was {thr_7d:,} in the last 7 days, with a latest MA7 of {thr_ma7:.1f}/day.")
    return insights[:4]


def _capacity_calendar_html(
    daily: pd.DataFrame,
    *,
    team: str,
    year: int,
    month: int,
) -> str:
    """
    Render a month calendar with weekends shaded.
    Expects daily columns: day (YYYY-MM-DD), effective_people, headcount_working.
    """
    cal = calendar.Calendar(firstweekday=0)  # Monday
    title = f"{team} · {year:04d}-{month:02d}"
    daily_map = {}
    window_min = None
    window_max = None
    if not daily.empty:
        days = pd.to_datetime(daily["day"].astype(str).str.slice(0, 10), errors="coerce").dt.date
        if days.notna().any():
            window_min = days.min()
            window_max = days.max()
        for _, r in daily.iterrows():
            d = str(r["day"])[:10]
            daily_map[d] = (
                float(r.get("effective_people", 0.0) or 0.0),
                int(r.get("headcount_working", 0) or 0),
            )

    dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    head = "".join(f"<th class='dow'>{x}</th>" for x in dow)

    rows = []
    for week in cal.monthdatescalendar(year, month):
        tds = []
        for d in week:
            in_month = d.month == month
            is_weekend = d.weekday() >= 5
            cls = []
            if not in_month:
                cls.append("out")
            if is_weekend:
                cls.append("weekend")
            key = d.isoformat()
            in_window = (
                (window_min is None or window_max is None)
                or (window_min <= d <= window_max)
            )
            if not in_window:
                cls.append("outwindow")
                eff, hc = (None, None)
            else:
                eff, hc = daily_map.get(key, (0.0, 0))
            body = ""
            if in_month:
                if eff is None or hc is None:
                    body = f"<div class='daynum'>{d.day}</div><div class='na'>—</div>"
                else:
                    body = (
                        f"<div class='daynum'>{d.day}</div>"
                        f"<div class='metric'>{eff:.1f}</div>"
                        f"<div class='sub'>{hc} ppl</div>"
                    )
            tds.append(f"<td class='{' '.join(cls)}'>{body}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")

    style = """
    <style>
      .capcal { width: 100%; border-collapse: collapse; font-family: system-ui, sans-serif; }
      .capcal th { text-align: center; padding: 6px 0; font-size: 12px; color: #555; border-bottom: 1px solid #eee; }
      .capcal td { border: 1px solid #eee; vertical-align: top; height: 64px; padding: 6px; }
      .capcal td.weekend { background: #f6f6f6; }
      .capcal td.out { background: #fafafa; color: #bbb; }
      .capcal td.outwindow { background: #fbfbfb; color: #b8b8b8; }
      .capcal .title { font-weight: 650; margin: 6px 0 10px; font-size: 14px; }
      .capcal .daynum { font-size: 12px; color: #666; }
      .capcal .metric { font-size: 18px; font-weight: 700; margin-top: 2px; }
      .capcal .sub { font-size: 11px; color: #777; margin-top: 2px; }
      .capcal .na { font-size: 16px; font-weight: 650; margin-top: 12px; color: #b8b8b8; }
    </style>
    """

    table = (
        f"{style}"
        f"<div class='title'>{html.escape(title)}</div>"
        f"<table class='capcal'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<div style='margin-top:6px;font-size:11px;color:#777'>Cell value: effective people (sum % / 100) · Footer: headcount working</div>"
    )
    return table


def _team_open_cases_chart(df: pd.DataFrame, *, team: str) -> None:
    work = df.query("team == @team").copy()
    if work.empty:
        st.info(f"No {team} workload rows for this filter.")
        return

    work["suggested_rebalance_flag"] = work["suggested_rebalance_flag"].fillna(False).astype(bool)
    work = work.sort_values(["open_cases_now", "p90_age_open_days"], ascending=[False, False])
    height = max(180, min(520, 34 * len(work)))
    chart = (
        alt.Chart(work)
        .mark_bar()
        .encode(
            x=alt.X("open_cases_now:Q", title="Open cases now"),
            y=alt.Y("actor:N", sort="-x", title=None),
            color=alt.Color(
                "suggested_rebalance_flag:N",
                title="Needs attention",
                scale=alt.Scale(domain=[False, True], range=["#8fb3ff", "#e45756"]),
            ),
            tooltip=[
                "actor",
                "team",
                "open_cases_now",
                "completed_7d",
                "completed_30d",
                alt.Tooltip("p90_age_open_days:Q", format=".1f", title="P90 open age days"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def _team_backlog_throughput_chart(df: pd.DataFrame) -> None:
    work = df.copy()
    if work.empty:
        st.info("No workload rows for this filter.")
        return

    work["actor_label"] = work["team"].astype(str) + " · " + work["actor"].astype(str)
    work["suggested_rebalance_flag"] = work["suggested_rebalance_flag"].fillna(False).astype(bool)
    chart = (
        alt.Chart(work)
        .mark_circle(opacity=0.9, size=80)
        .encode(
            x=alt.X("completed_7d:Q", title="Completed last 7 days"),
            y=alt.Y("open_cases_now:Q", title="Open cases now"),
            size=alt.Size("completed_30d:Q", title="Completed 30d", scale=alt.Scale(range=[40, 300])),
            color=alt.Color(
                "p90_age_open_days:Q",
                title="P90 open age (days)",
                scale=alt.Scale(scheme="orangered", reverse=True),
            ),
            shape=alt.Shape("team:N", title="Team"),
            tooltip=[
                "actor_label",
                "open_cases_now",
                "completed_7d",
                "completed_30d",
                alt.Tooltip("p90_age_open_days:Q", format=".1f", title="P90 open age days"),
            ],
        )
        .properties(height=360)
    )
    st.caption("Point colour encodes p90 open age; size is completions in the last 30 days.")
    st.altair_chart(chart, width="stretch")


def _team_workload_exceptions(df: pd.DataFrame, *, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    work = df.copy()
    for col in ["open_cases_now", "completed_7d", "completed_30d", "p90_age_open_days"]:
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
    work["suggested_rebalance_flag"] = work["suggested_rebalance_flag"].fillna(False).astype(bool)

    open_threshold = float(work["open_cases_now"].quantile(0.75)) if len(work) else 0.0
    high_open = work["open_cases_now"] >= max(1.0, open_threshold)
    high_age = work["p90_age_open_days"] >= 2.0
    low_recent_output = high_open & (work["completed_7d"] == 0)

    def _reason(row: pd.Series) -> str:
        reasons: list[str] = []
        if bool(row["suggested_rebalance_flag"]):
            reasons.append("above team rebalance threshold")
        if float(row["p90_age_open_days"]) >= 2.0:
            reasons.append("p90 open age >= 2 days")
        if float(row["open_cases_now"]) >= max(1.0, open_threshold) and int(row["completed_7d"]) == 0:
            reasons.append("high open load with no 7d completions")
        return "; ".join(reasons)

    work = work.loc[work["suggested_rebalance_flag"] | high_age | low_recent_output].copy()
    if work.empty:
        return pd.DataFrame()

    work["reason"] = work.apply(_reason, axis=1)
    work = work.sort_values(
        ["suggested_rebalance_flag", "p90_age_open_days", "open_cases_now"],
        ascending=[False, False, False],
    )
    return work[
        [
            "team",
            "actor",
            "open_cases_now",
            "completed_7d",
            "completed_30d",
            "p90_age_open_days",
            "reason",
        ]
    ].head(int(limit))


def _bottleneck_score_chart(df: pd.DataFrame) -> None:
    work = df.query("wip_now > 0 or bottleneck_score > 0").head(12).copy()
    if work.empty:
        st.info("No bottleneck signal for this filter.")
        return
    work["stage"] = work["step_label"].astype(str).str.slice(0, 58)
    chart = (
        alt.Chart(work)
        .mark_bar()
        .encode(
            x=alt.X("bottleneck_score:Q", title="Bottleneck score"),
            y=alt.Y("stage:N", sort="-x", title=None),
            color=alt.Color("wip_now:Q", title="WIP now"),
            tooltip=[
                "step_label",
                "wip_now",
                "net_7d",
                alt.Tooltip("p90_dwell_hours:Q", format=".1f", title="P90 dwell hours"),
                alt.Tooltip("bottleneck_score:Q", format=".2f", title="Score"),
            ],
        )
        .properties(height=max(220, min(520, 34 * len(work))))
    )
    st.altair_chart(chart, width="stretch")


def _bottleneck_aging_chart(df: pd.DataFrame) -> None:
    cols = ["aging_0_24h", "aging_1_3d", "aging_3_7d", "aging_7d_plus"]
    work = df.query("wip_now > 0").head(10).copy()
    if work.empty:
        st.info("No open WIP aging signal for this filter.")
        return
    long = work[["step_label", *cols]].melt(
        id_vars=["step_label"],
        value_vars=cols,
        var_name="age_bucket",
        value_name="applications",
    )
    labels = {
        "aging_0_24h": "0-24h",
        "aging_1_3d": "1-3d",
        "aging_3_7d": "3-7d",
        "aging_7d_plus": "7d+",
    }
    long["age_bucket"] = long["age_bucket"].map(labels)
    long["stage"] = long["step_label"].astype(str).str.slice(0, 48)
    chart = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("applications:Q", title="Applications"),
            y=alt.Y("stage:N", title=None, sort=work["step_label"].astype(str).str.slice(0, 48).tolist()),
            color=alt.Color("age_bucket:N", title="Age"),
            tooltip=["step_label", "age_bucket", "applications"],
        )
        .properties(height=max(220, min(480, 32 * work["step_label"].nunique())))
    )
    st.altair_chart(chart, width="stretch")


def _rework_product_chart(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No rework rows by product for this filter.")
        return
    work = df.copy()
    work["loop_rate_pct"] = 100.0 * work["n_apps_2plus_interactions"] / work["n_apps_total"].replace(0, pd.NA)
    chart = (
        alt.Chart(work)
        .mark_bar()
        .encode(
            x=alt.X("loop_rate_pct:Q", title="% with 2+ interactions"),
            y=alt.Y("product_type:N", sort="-x", title=None),
            tooltip=[
                "product_type",
                "n_apps_total",
                "n_apps_2plus_interactions",
                alt.Tooltip("loop_rate_pct:Q", format=".1f", title="Loop rate %"),
                alt.Tooltip("pct_first_pass:Q", format=".1f", title="First pass %"),
            ],
        )
        .properties(height=max(160, 44 * len(work)))
    )
    st.altair_chart(chart, width="stretch")


def _overview_sla_stacked_bars(sla: pd.DataFrame) -> None:
    if sla.empty:
        return
    order_status = ["breached", "at_risk", "ok"]
    colors = {
        "breached": "#e45756",
        "at_risk": "#f58518",
        "ok": "#54a24b",
    }
    # Shorter axis labels (full SQL name in tooltip); avoids Vega auto-rotating cramped X ordinals.
    _sla_area_axis_labels: dict[str, str] = {
        "Offer & onboarding": "Offer / onboard",
        "Interaction / RFI": "RFI / interaction",
        "CR review": "CR review",
        "Compliance": "Compliance",
        "Other": "Other",
    }
    work = sla.copy()
    work["_area_lbl"] = work["sla_area"].astype(str).map(lambda s: _sla_area_axis_labels.get(s, s))
    pipeline_order = ["CR review", "Compliance", "Interaction / RFI", "Offer & onboarding", "Other"]
    sort_lbl = [_sla_area_axis_labels[k] for k in pipeline_order if k in set(work["sla_area"].astype(str))]
    for s in work["_area_lbl"].unique():
        if s not in sort_lbl:
            sort_lbl.append(str(s))

    n_areas = max(1, int(work["sla_area"].nunique()))
    # Horizontal stacked bars: categories on Y → area names are always horizontal text.
    c = (
        alt.Chart(work)
        .mark_bar()
        .encode(
            y=alt.Y(
                "_area_lbl:N",
                title="SLA area",
                sort=sort_lbl,
                axis=alt.Axis(
                    labelAngle=0,
                    labelLimit=0,
                    labelOverlap=False,
                    labelPadding=6,
                    titleAngle=0,
                    titlePadding=8,
                    titleAlign="right",
                ),
            ),
            x=alt.X(
                "n_applications:Q",
                title="In-flight apps",
                stack="zero",
                axis=alt.Axis(
                    titleAngle=0,
                    labelAngle=0,
                    labelFlush=False,
                    titlePadding=10,
                ),
            ),
            color=alt.Color(
                "status:N",
                title="Status",
                sort=order_status,
                scale=alt.Scale(
                    domain=order_status,
                    range=[colors["breached"], colors["at_risk"], colors["ok"]],
                ),
                legend=alt.Legend(orient="top", direction="horizontal", title=None, padding=4),
            ),
            tooltip=["sla_area", "_area_lbl", "status", "n_applications"],
        )
        .properties(height=max(160, min(420, 56 * n_areas)))
        .configure_axisX(labelAngle=0)
        .configure_axisY(labelAngle=0)
    )
    st.altair_chart(c, width="stretch")


def _throughput_daily_chart(thr: pd.DataFrame) -> None:
    if thr.empty or "n_terminated" not in thr.columns:
        return
    thr = thr.copy()
    thr["day"] = pd.to_datetime(thr["day"], utc=True, errors="coerce")
    tline = (
        alt.Chart(thr)
        .mark_line(interpolate="monotone", strokeWidth=1.2)
        .encode(
            x=alt.X("day:T", title="Date"),
            y=alt.Y("n_terminated:Q", title="Terminal / day"),
            tooltip=[alt.Tooltip("day:T", title="Day"), "n_terminated"],
        )
    )
    mline = (
        alt.Chart(thr)
        .mark_line(
            color="#94a3b8",
            strokeWidth=1,
            strokeDash=[4, 3],
        )
        .encode(
            x=alt.X("day:T", title="Date"),
            y=alt.Y("n_terminated_ma7:Q", title=""),
            tooltip=[alt.Tooltip("day:T", title="Day"), "n_terminated_ma7"],
        )
    )
    c = tline + mline
    c = c.properties(height=200)
    st.altair_chart(c, width="stretch")


def _cohort_in_flight_line(kpi_df: pd.DataFrame) -> None:
    if kpi_df.empty or "pct_in_flight_as_of" not in kpi_df.columns:
        return
    c = (
        alt.Chart(kpi_df)
        .mark_line(point=True, strokeWidth=1.1)
        .encode(
            x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
            y=alt.Y("pct_in_flight_as_of:Q", title="% in-flight (as of)"),
            tooltip=[
                "cohort_month",
                "n_applications",
                alt.Tooltip("pct_in_flight_as_of:Q", format=".1f", title="% in-flight"),
            ],
        )
        .properties(height=240)
    )
    st.altair_chart(c, width="stretch")


def _cohort_survival_lines(surv: pd.DataFrame) -> None:
    if surv.empty:
        return
    long = surv.melt(
        id_vars=["cohort_month", "n_apps"],
        value_vars=["pct_alive_7d", "pct_alive_14d", "pct_alive_30d", "pct_alive_60d"],
        var_name="horizon",
        value_name="pct_alive",
    )
    hmap = {
        "pct_alive_7d": "+7d",
        "pct_alive_14d": "+14d",
        "pct_alive_30d": "+30d",
        "pct_alive_60d": "+60d",
    }
    long["horizon"] = long["horizon"].map(hmap)
    c = (
        alt.Chart(long)
        .mark_line(point=True)
        .encode(
            x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
            y=alt.Y("pct_alive:Q", title="% still in-flight (survival)"),
            color=alt.Color("horizon:N", title="Window"),
            tooltip=[
                "cohort_month",
                "horizon",
                "n_apps",
                alt.Tooltip("pct_alive:Q", format=".1f", title="pct alive"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(c, width="stretch")


def _cohort_time_to_offer_bars(tto: pd.DataFrame) -> None:
    if tto.empty:
        return
    long = tto.melt(
        id_vars=["cohort_month", "n_with_offer"],
        value_vars=["p50_days_to_offer", "p90_days_to_offer"],
        var_name="metric",
        value_name="days",
    )
    lab = {
        "p50_days_to_offer": "p50",
        "p90_days_to_offer": "p90",
    }
    long["metric"] = long["metric"].map(lab)
    c = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
            y=alt.Y("days:Q", title="Days to first offer"),
            xOffset="metric:N",
            color=alt.Color("metric:N", title=""),
            tooltip=["cohort_month", "n_with_offer", "metric", alt.Tooltip("days:Q", format=".1f")],
        )
        .properties(height=260)
    )
    st.altair_chart(c, width="stretch")


def _cohort_stage_heatmap(snap: pd.DataFrame) -> None:
    if snap.empty:
        return
    c = (
        alt.Chart(snap)
        .mark_rect()
        .encode(
            x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
            y=alt.Y("step_order:O", title="Stage (order)"),
            color=alt.Color("n_applications:Q", title="Apps", scale=alt.Scale(scheme="blues")),
            tooltip=["cohort_month", "step_order", "n_applications"],
        )
        .properties(height=min(480, 14 * snap["step_order"].nunique()))
    )
    st.altair_chart(c, width="stretch")


def _cohort_multi_trajectory_charts(multi: pd.DataFrame) -> None:
    if multi.empty:
        return
    a, b = st.columns(2)
    with a:
        st.caption("In-flight % by cohort month")
        c1 = (
            alt.Chart(multi)
            .mark_line(point=True)
            .encode(
                x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
                y=alt.Y("pct_in_flight_as_of:Q", title="% in-flight (as of)"),
                tooltip=["cohort_month", "n_apps", "pct_in_flight_as_of"],
            )
            .properties(height=220)
        )
        st.altair_chart(c1, width="stretch")
    with b:
        mlt = multi.melt(
            id_vars=["cohort_month"],
            value_vars=["pct_alive_7d", "pct_alive_14d", "pct_alive_30d", "pct_alive_60d"],
            var_name="horizon",
            value_name="pct",
        )
        hmap = {
            "pct_alive_7d": "+7d",
            "pct_alive_14d": "+14d",
            "pct_alive_30d": "+30d",
            "pct_alive_60d": "+60d",
        }
        mlt["horizon"] = mlt["horizon"].map(hmap)
        st.caption("Survival % by horizon and cohort")
        c2 = (
            alt.Chart(mlt)
            .mark_line(point=True)
            .encode(
                x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
                y=alt.Y("pct:Q", title="% (survival)"),
                color=alt.Color("horizon:N", title="Horizon"),
            )
            .properties(height=220)
        )
        st.altair_chart(c2, width="stretch")
    tto2 = multi.dropna(subset=["p50_days_to_offer"], how="all")
    if not tto2.empty and "p50_days_to_offer" in tto2.columns:
        tlong = tto2.melt(
            id_vars=["cohort_month"],
            value_vars=[c for c in ("p50_days_to_offer", "p90_days_to_offer") if c in tto2.columns],
            var_name="q",
            value_name="days",
        )
        tlong["q"] = tlong["q"].map({"p50_days_to_offer": "p50", "p90_days_to_offer": "p90"})
        tlong = tlong.dropna(subset=["days"])
        if not tlong.empty:
            st.caption("Time to first offer (p50 / p90) for cohorts with an offer in window")
            c3 = (
                alt.Chart(tlong)
                .mark_line(point=True)
                .encode(
                    x=alt.X("cohort_month:T", title="Cohort (anchor month)"),
                    y=alt.Y("days:Q", title="Days to first offer"),
                    color=alt.Color("q:N", title=""),
                )
                .properties(height=220)
            )
            st.altair_chart(c3, width="stretch")


def _period_start_end_grouped_bars(
    start_df: pd.DataFrame,
    end_df: pd.DataFrame,
    *,
    top_n: int = 14,
) -> None:
    if start_df.empty and end_df.empty:
        return
    s = (
        start_df.rename(columns={"active_applications": "start_n"})[
            ["step_order", "step_label", "start_n"]
        ].copy()
        if not start_df.empty
        else pd.DataFrame(columns=["step_order", "step_label", "start_n"])
    )
    e = (
        end_df.rename(columns={"active_applications": "end_n"})[
            ["step_order", "step_label", "end_n"]
        ].copy()
        if not end_df.empty
        else pd.DataFrame(columns=["step_order", "step_label", "end_n"])
    )
    m = s.merge(
        e,
        on=["step_order", "step_label"],
        how="outer",
    ).fillna(0.0)
    m["max_pair"] = m[["start_n", "end_n"]].max(axis=1)
    m = m.sort_values("max_pair", ascending=False).head(int(top_n))
    long = m.melt(
        id_vars=["step_label", "step_order"],
        value_vars=["start_n", "end_n"],
        var_name="which",
        value_name="n",
    )
    long["which"] = long["which"].map({"start_n": "Start snapshot", "end_n": "End snapshot"})
    c = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            y=alt.Y("step_label:N", sort=alt.EncodingSortField(field="n", op="max", order="descending"), title="Stage"),
            x=alt.X("n:Q", title="Applications"),
            color=alt.Color("which:N", title=""),
            yOffset="which:N",
            tooltip=["step_label", "which", "n", "step_order"],
        )
        .properties(height=min(420, 28 * long["step_label"].nunique()))
    )
    st.altair_chart(c, width="stretch")


def _period_arrivals_losses_by_day(daily: pd.DataFrame) -> None:
    if daily.empty or "day" not in daily.columns:
        return
    w = daily.copy()
    w["day"] = pd.to_datetime(w["day"], errors="coerce")
    w["series_display"] = (
        w["series"]
        .map(
            {
                "arrivals": "Arrivals",
                "losses": "Terminal events",
            }
        )
        .fillna(w["series"].astype(str))
    )
    c = (
        alt.Chart(w)
        .mark_line(interpolate="monotone", point=True, strokeWidth=1.1)
        .encode(
            x=alt.X("day:T", title="Day"),
            y=alt.Y(
                "n:Q",
                title="Count per day",
                axis=alt.Axis(
                    titleAngle=0,
                    titleAlign="left",
                    titleAnchor="start",
                    titleY=-22,
                    titleX=-8,
                ),
            ),
            color=alt.Color(
                "series_display:N",
                title=None,
                scale=alt.Scale(domain=["Arrivals", "Terminal events"], range=["#4c78a8", "#e45756"]),
                legend=alt.Legend(
                    orient="top",
                    direction="horizontal",
                    title=None,
                    labelFontSize=12,
                    symbolType="circle",
                    padding=4,
                ),
            ),
            tooltip=[
                alt.Tooltip("day:T", title="Day"),
                alt.Tooltip("series_display:N", title="Series"),
                alt.Tooltip("n:Q", title="Count"),
            ],
        )
        .properties(height=240, padding={"top": 36})
    )
    st.altair_chart(c, width="stretch")


def _team_closures_heatmap(comp: pd.DataFrame, *, top_actors: int = 12) -> None:
    if comp.empty:
        return
    tot = comp.groupby("actor", as_index=False)["n_completions"].sum()
    top = set(
        tot.sort_values("n_completions", ascending=False)
        .head(int(top_actors))["actor"]
        .astype(str)
        .tolist()
    )
    w = comp.loc[comp["actor"].astype(str).isin(top)].copy()
    if w.empty:
        st.info("No completion rows for an actor heatmap in this window.")
        return
    w["day"] = pd.to_datetime(w["day"], errors="coerce")
    w["label"] = w["team"].astype(str) + " · " + w["actor"].astype(str)
    w["__tot"] = w.groupby("label", observed=True)["n_completions"].transform("sum")
    w = w.sort_values(["__tot", "label", "day"], ascending=[False, True, True])
    order = w["label"].unique().tolist()
    c = (
        alt.Chart(w)
        .mark_rect()
        .encode(
            x=alt.X("day:T", title="Day"),
            y=alt.Y("label:N", title="Actor", sort=order),
            color=alt.Color("n_completions:Q", title="Completions", scale=alt.Scale(scheme="tealblues")),
            tooltip=["day", "actor", "team", "n_completions"],
        )
        .properties(height=min(420, 22 * w["label"].nunique()))
    )
    st.caption("Top actors by total completions in the window; each cell is distinct apps closed that day.")
    st.altair_chart(c, width="stretch")


def _rework_interaction_dist_chart(dist: pd.DataFrame) -> None:
    if dist.empty:
        return
    c = (
        alt.Chart(dist)
        .mark_bar()
        .encode(
            x=alt.X("interaction_bucket:N", title="Interaction loops (started)", sort=None),
            y=alt.Y("n_apps:Q", title="Applications"),
            tooltip=["interaction_bucket", "n_apps"],
        )
        .properties(height=220)
    )
    st.altair_chart(c, width="stretch")


def _investigator_staged_gantt(staged: pd.DataFrame) -> None:
    if len(staged) < 2:
        return
    staged = staged.sort_values("timestamp").reset_index(drop=True)
    rows: list[dict] = []
    for i in range(len(staged) - 1):
        t0 = pd.Timestamp(staged.loc[i, "timestamp"])
        t1 = pd.Timestamp(staged.loc[i + 1, "timestamp"])
        stord = int(staged.loc[i, "stage_order"])
        rows.append(
            {
                "t0": t0,
                "t1": t1,
                "stage_key": f"{stord:02d}",
                "stage_order": stord,
            }
        )
    segs = pd.DataFrame(rows)
    if segs.empty:
        return
    y_order = [f"{i:02d}" for i in sorted(segs["stage_order"].unique().tolist())]
    c = (
        alt.Chart(segs)
        .mark_bar()
        .encode(
            y=alt.Y("stage_key:N", sort=y_order, title="Stage (order at segment start)"),
            x=alt.X("t0:T", title=""),
            x2=alt.X2("t1:T"),
            tooltip=["stage_key", alt.Tooltip("t0:T", title="From"), alt.Tooltip("t1:T", title="To")],
        )
        .properties(height=min(520, 32 * segs["stage_key"].nunique()))
    )
    st.altair_chart(c, width="stretch")


def _capacity_fte_sweep_chart(
    *,
    inflow: float,
    current_cycle_time: float,
    base_fte: float,
    backlog: float,
) -> None:
    from analytics.capacity import project_cycle_time_days, project_wip

    rows: list[dict] = []
    for total_fte in range(1, 41):
        pct = project_cycle_time_days(
            float(current_cycle_time),
            base_fte=float(base_fte),
            new_fte=float(total_fte),
        )
        wip = project_wip(float(inflow), float(pct))
        rows.append(
            {
                "total_fte": total_fte,
                "projected_wip": wip,
                "projected_ct": pct,
            }
        )
    dfp = pd.DataFrame(rows)
    c1 = (
        alt.Chart(dfp)
        .mark_line()
        .encode(
            x=alt.X("total_fte:O", title="Total FTE (1–40)"),
            y=alt.Y("projected_wip:Q", title="Steady-state WIP (apps)"),
        )
    )
    c2 = (
        alt.Chart(dfp)
        .mark_line()
        .encode(
            x=alt.X("total_fte:O", title="Total FTE (1–40)"),
            y=alt.Y("projected_ct:Q", title="Projected cycle time p50 (days)"),
        )
    )
    st.caption("Sweep assumes the same inflow, baseline FTE, and current cycle time as above; FTE = CR + Compliance.")
    a, b = st.columns(2)
    with a:
        st.altair_chart(c1.properties(height=220), width="stretch")
    with b:
        st.altair_chart(c2.properties(height=220), width="stretch")


def _bottleneck_inflow_outflow_chart(radar: pd.DataFrame) -> None:
    work = (
        radar.query("wip_now > 0 or inflow_7d > 0 or outflow_7d > 0")
        .sort_values("wip_now", ascending=False)
        .head(12)
        .copy()
    )
    if work.empty:
        st.info("No inflow/outflow in this view.")
        return
    work["stage"] = work["step_label"].astype(str).str.slice(0, 52)
    long = work.melt(
        id_vars=["stage", "step_label", "net_7d"],
        value_vars=["inflow_7d", "outflow_7d"],
        var_name="flow",
        value_name="n",
    )
    long["flow"] = long["flow"].map({"inflow_7d": "Transitions in (7d)", "outflow_7d": "Transitions out (7d)"})
    c = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            y=alt.Y("stage:N", title=None, sort=alt.EncodingSortField(field="n", op="sum", order="descending")),
            x=alt.X("n:Q", title="Transition events (7d, last week of window)"),
            color=alt.Color("flow:N", title=""),
            yOffset=alt.YOffset("flow:N"),
            tooltip=["step_label", "flow", "n", "net_7d"],
        )
        .properties(height=max(200, 28 * work["step_label"].nunique()))
    )
    st.caption("Last 7 days of the selected window, per bottleneck_radar inflow_7d / outflow_7d (event counts, not unique apps).")
    st.altair_chart(c, width="stretch")


def _period_net_stage_delta_chart(start_df: pd.DataFrame, end_df: pd.DataFrame) -> None:
    if start_df.empty and end_df.empty:
        return
    s = (
        start_df.rename(columns={"active_applications": "start_n"})[
            ["step_order", "step_label", "start_n"]
        ]
        if not start_df.empty
        else pd.DataFrame(columns=["step_order", "step_label", "start_n"])
    )
    e = (
        end_df.rename(columns={"active_applications": "end_n"})[
            ["step_order", "step_label", "end_n"]
        ]
        if not end_df.empty
        else pd.DataFrame(columns=["step_order", "step_label", "end_n"])
    )
    m = s.merge(e, on=["step_order", "step_label"], how="outer").fillna(0.0)
    m["delta"] = m["end_n"] - m["start_n"]
    m = m.assign(_absd=m["delta"].abs()).sort_values("_absd", ascending=False).head(18).drop(columns=["_absd"])
    m["label"] = m["step_label"].astype(str).str.slice(0, 56)
    c = (
        alt.Chart(m)
        .mark_bar()
        .encode(
            y=alt.Y("label:N", sort=alt.EncodingSortField(field="delta", order="ascending"), title="Stage"),
            x=alt.X("delta:Q", title="Δ apps (end snapshot − start snapshot)"),
            color=alt.condition(alt.datum.delta > 0, alt.value("#4c78a8"), alt.value("#e45756")),
            tooltip=["step_label", "start_n", "end_n", "delta", "step_order"],
        )
        .properties(height=min(440, 26 * len(m)))
    )
    st.caption("Largest absolute moves in stage mix; blue = more apps in bucket at end than start, red = fewer.")
    st.altair_chart(c, width="stretch")


def _rework_outcome_offer_rate_chart(outcome: pd.DataFrame) -> None:
    if outcome.empty or "n_reached_offer" not in outcome.columns:
        return
    w = outcome.copy()
    w["pct_reached_offer"] = 100.0 * w["n_reached_offer"].astype(float) / w["n_apps"].replace(0, pd.NA).astype(float)
    c = (
        alt.Chart(w)
        .mark_bar()
        .encode(
            x=alt.X("interaction_bucket:N", title="Interaction loops (started)", sort=None),
            y=alt.Y("pct_reached_offer:Q", title="% of cohort with OFFER_SENT (ever)"),
            tooltip=["interaction_bucket", "n_apps", "n_reached_offer", alt.Tooltip("pct_reached_offer:Q", format=".1f")],
        )
        .properties(height=240)
    )
    st.caption("Share of **cohort** apps in each loop bucket that have at least one OFFER_SENT in history (any time).")
    st.altair_chart(c, width="stretch")


def _team_actor_outcome_chart(outcomes: pd.DataFrame) -> None:
    if outcomes.empty:
        return
    w = outcomes.copy()
    top = w.assign(
        n_tot=w["n_approved"] + w["n_rejected"] + w["n_other_terminal"]
    ).sort_values("n_tot", ascending=False).head(14)
    long = top.melt(
        id_vars=["actor", "team"],
        value_vars=["n_approved", "n_rejected", "n_other_terminal"],
        var_name="outcome",
        value_name="n",
    )
    long["outcome"] = long["outcome"].map(
        {
            "n_approved": "Master data (approved)",
            "n_rejected": "Rejected",
            "n_other_terminal": "Cancelled / refused",
        }
    )
    long["label"] = long["team"].astype(str) + " · " + long["actor"].astype(str)
    c = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            y=alt.Y("label:N", title=None, sort=alt.EncodingSortField(field="n", op="sum", order="descending")),
            x=alt.X("n:Q", title="Completions in last 30d of window"),
            color=alt.Color("outcome:N", title=""),
            yOffset=alt.YOffset("outcome:N"),
        )
        .properties(height=min(420, 28 * long["label"].nunique() // 3 + 4))
    )
    st.caption("Terminal mix by actor (30d lookback, same as team_workload).")
    st.altair_chart(c, width="stretch")


def _capacity_scenario_bars(
    *,
    backlog: float,
    projected_wip: float,
    current_ct: float,
    projected_ct: float,
    cr_fte: int,
    compliance_fte: int,
) -> None:
    s1 = (
        alt.Chart(
            pd.DataFrame(
                {
                    "metric": ["Backlog (now)", "Steady-state WIP (scenario)"],
                    "value": [backlog, projected_wip],
                }
            )
        )
        .mark_bar()
        .encode(
            x=alt.X("metric:N", title=""),
            y=alt.Y("value:Q", title="Apps"),
            color=alt.Color("metric:N", title="", legend=None, scale=alt.Scale(range=["#94a3b8", "#4c78a8"])),
            tooltip=["metric", "value"],
        )
        .properties(height=220, width=320)
    )
    s2 = (
        alt.Chart(
            pd.DataFrame(
                {
                    "metric": ["Current CT (days)", "Projected CT (days)"],
                    "value": [current_ct, projected_ct],
                }
            )
        )
        .mark_bar()
        .encode(
            x=alt.X("metric:N", title=""),
            y=alt.Y("value:Q", title="Days"),
            color=alt.Color("metric:N", title="", legend=None, scale=alt.Scale(range=["#a8b0bc", "#f58518"])),
        )
        .properties(height=220, width=320)
    )
    fte = (
        alt.Chart(
            pd.DataFrame(
                {
                    "team": ["CR FTE", "Compliance FTE"],
                    "fte": [float(cr_fte), float(compliance_fte)],
                }
            )
        )
        .mark_bar()
        .encode(x=alt.X("team:N", title=""), y=alt.Y("fte:Q", title="FTE"), color=alt.Color("team:N", title="", legend=None))
        .properties(height=220, width=220)
    )
    a, b, d = st.columns(3)
    with a:
        st.altair_chart(s1, width="stretch")
    with b:
        st.altair_chart(s2, width="stretch")
    with d:
        st.altair_chart(fte, width="stretch")


def _sla_weekly_heatmap(trend: pd.DataFrame) -> None:
    if trend.empty or "week" not in trend.columns:
        return
    w = trend.copy()
    w["cell"] = w["pct_within"].clip(0, 100)
    c = (
        alt.Chart(w)
        .mark_rect()
        .encode(
            x=alt.X("week:O", title="Week"),
            y=alt.Y("sla_name:N", title="SLA"),
            color=alt.Color("cell:Q", title="% within", scale=alt.Scale(scheme="greenblue")),
            tooltip=["week", "sla_name", alt.Tooltip("pct_within:Q", format=".1f")],
        )
        .properties(height=200)
    )
    st.caption("Weekly % within (same definition as the line chart; darker is higher).")
    st.altair_chart(c, width="stretch")


def _investigator_dwell_with_cohort_median(
    dwell: pd.DataFrame,
    medians: pd.DataFrame,
) -> None:
    dplot = dwell.copy()
    dplot["stage_label"] = dplot["stage_label"].fillna(dplot["stage_order"].astype(str))
    dplot = dplot.sort_values("stage_order", ascending=True)
    if medians is not None and not medians.empty and "median_dwell_hours" in medians.columns:
        m = medians[["stage_order", "median_dwell_hours"]].copy()
        dplot = dplot.merge(m, on="stage_order", how="left")
    ysort = dplot.drop_duplicates("stage_order").sort_values("stage_order")["stage_label"].astype(str).tolist()
    bars = (
        alt.Chart(dplot)
        .mark_bar(color="#4c78a8", opacity=0.88)
        .encode(
            x=alt.X("dwell_hours:Q", title="Hours in stage (completed segments)"),
            y=alt.Y("stage_label:N", sort=ysort, title="Stage"),
            tooltip=["stage_label", alt.Tooltip("dwell_hours:Q", format=".1f", title="This application")],
        )
    )
    if "median_dwell_hours" in dplot.columns and dplot["median_dwell_hours"].notna().any():
        pts = dplot.loc[dplot["median_dwell_hours"].notna()].copy()
        points = (
            alt.Chart(pts)
            .mark_point(color="#e45756", size=70, shape="diamond", filled=True)
            .encode(
                x=alt.X("median_dwell_hours:Q", title="Hours in stage (completed segments)"),
                y=alt.Y("stage_label:N", sort=ysort, title="Stage"),
                tooltip=[alt.Tooltip("median_dwell_hours:Q", format=".1f", title="Cohort median (same product)")],
            )
        )
        c = bars + points
    else:
        c = bars
    st.caption("Bars: this application. Diamonds: **median** hours among completed stage segments in the product filter (across all applications).")
    st.altair_chart(
        c.properties(height=min(520, max(200, 22 * len(dplot)))),
        width="stretch",
    )


"""
Relio Operations Intelligence — Streamlit dashboard (DuckDB + QueryManager).

Run from repository root:
  streamlit run app/main.py
"""

from __future__ import annotations

import os
import sys
import calendar
from pathlib import Path

import html

import altair as alt
import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from streamlit.column_config import DatetimeColumn, TextColumn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics.legend import subtitle as legend_subtitle  # noqa: E402
from analytics.period_dashboard import load_period_dashboard  # noqa: E402
from analytics.query_manager import QueryManager  # noqa: E402
from analytics.team_productivity import (  # noqa: E402
    generate_staffing_calendar,
    generate_team_roster,
)

DEFAULT_DB = PROJECT_ROOT / "data" / "relio_analytics.db"

TERMINAL_ACTIONS = (
    "MASTER_DATA_SUBMITTED",
    "APPLICATION_REJECTED",
    "APPLICATION_CANCELLED",
    "OFFER_REFUSED",
)

# Funnel step_order for terminal buckets (aligned with funnel_overview labels).
TERMINAL_STEP_ORDERS = frozenset({17, 18, 22, 26})

LOOP_ACTIONS = frozenset(
    {
        "COMPLIANCE_REVIEW_STARTED",
        "INTERACTION_STARTED",
        "INTERACTION_SUBMITTED",
        "ANSWERS_EDIT_STARTED",
    }
)

KPI_ACTIVE_SQL = """
WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.action AS current_action
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
)
SELECT COUNT(*)::BIGINT AS n
FROM latest
WHERE current_action NOT IN (
    'MASTER_DATA_SUBMITTED',
    'APPLICATION_REJECTED',
    'APPLICATION_CANCELLED',
    'OFFER_REFUSED'
);
"""

KPI_AVG_PROCESSING_SQL = """
WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
started AS (
    SELECT
        a.application_id,
        MIN(a.timestamp) AS started_at
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND a.action = 'APPLICATION_STARTED'
    GROUP BY a.application_id
),
last_ts AS (
    SELECT
        a.application_id,
        MAX(a.timestamp) AS last_at
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY a.application_id
)
SELECT
    AVG(date_diff('day', s.started_at, l.last_at))::DOUBLE AS avg_days
FROM started AS s
INNER JOIN last_ts AS l USING (application_id)
WHERE s.started_at IS NOT NULL;
"""

KPI_DENOM_SQL = """
WITH filtered AS (
    SELECT *
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
)
SELECT COUNT(DISTINCT application_id)::BIGINT AS n FROM filtered;
"""


def _connect_readonly(db_path: Path, *, db_mtime_ns: int) -> duckdb.DuckDBPyConnection:
    if not db_path.is_file():
        raise FileNotFoundError(
            f"Database not found: {db_path}. Run: python scripts/db_setup.py"
        )
    return duckdb.connect(str(db_path), read_only=True)


def _bootstrap_demo_duckdb(*, repo_root: Path, db_path: Path) -> None:
    """
    Streamlit Cloud / fresh clones often ship without data/relio_analytics.db (gitignored).
    Generate a small synthetic dataset + build DuckDB locally on first boot.

    Optional Streamlit secrets (toml):
      [bootstrap]
      n_applications = 1000
      seed = 42
      start_date = "2026-01-01"
      timeline_end = "2026-04-24T18:00:00"
      no_timeline_anchor = false
      no_carryover = false
      carryover_ratio = 0.70
    """
    if os.environ.get("RELIO_SKIP_BOOTSTRAP", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        return

    csv_path = (repo_root / "data" / "synthetic_logs.csv").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    cfg: dict[str, object] = {}
    try:
        cfg = dict(st.secrets.get("bootstrap", {}))  # type: ignore[arg-type]
    except Exception:
        cfg = {}

    n_apps = int(cfg.get("n_applications", 1000))
    seed = int(cfg.get("seed", 42))
    start_date = str(cfg.get("start_date", "2026-01-01"))
    timeline_end = str(cfg.get("timeline_end", "2026-04-24T18:00:00"))
    no_timeline_anchor = bool(cfg.get("no_timeline_anchor", False))
    no_carryover = bool(cfg.get("no_carryover", False))
    carryover_ratio = float(cfg.get("carryover_ratio", 0.70))

    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from synthetic_generator import generate_synthetic_audit_log, write_audit_outputs  # noqa: WPS433

    df = generate_synthetic_audit_log(
        n_applications=n_apps,
        seed=seed,
        start_date=start_date,
        timeline_end=None if no_timeline_anchor else timeline_end,
        anchor_timelines=not no_timeline_anchor,
        apply_carryover_for_period_demo=not no_carryover,
        carryover_ratio=carryover_ratio,
    )
    parquet_path = (repo_root / "data" / "synthetic_audit_log.parquet").resolve()
    write_audit_outputs(df, parquet_path=str(parquet_path), duckdb_csv_path=str(csv_path))

    from analytics.ddl_loader import apply_ddl  # noqa: WPS433

    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP VIEW IF EXISTS v_transitions;")
        con.execute("DROP VIEW IF EXISTS v_audit_staged;")
        con.execute("DROP TABLE IF EXISTS audit_logs;")
        con.execute(
            """
            CREATE TABLE audit_logs AS
            SELECT * FROM read_csv_auto(?, header = true)
            """,
            [str(csv_path)],
        )
        apply_ddl(con, repo_root)
    finally:
        con.close()


def _sidebar_product_options(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.sql("SELECT DISTINCT product_type FROM audit_logs ORDER BY 1").fetchall()
    return ["(All)"] + [r[0] for r in rows if r[0]]


def _sidebar_date_bounds(con: duckdb.DuckDBPyConnection) -> tuple:
    return con.sql(
        "SELECT min(timestamp)::DATE, max(timestamp)::DATE FROM audit_logs"
    ).fetchone()


def _parse_product_filter(choice: str) -> str | None:
    return None if choice == "(All)" else choice


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


def _transition_sankey(
    edges: pd.DataFrame,
    *,
    stage_label: dict[int, str],
    top_k: int,
    min_apps: int,
    include_self_loops: bool,
    compact_node_labels: bool,
) -> None:
    """
    Sankey of stage-to-stage movement.

    Input edges must have columns: from_stage, to_stage, n_apps (unique apps per edge).
    """
    if edges.empty:
        st.info("No stage-to-stage movement inside this window for the current cohort.")
        return

    work = edges.copy()
    if not include_self_loops:
        work = work.loc[work["from_stage"] != work["to_stage"]].copy()
    work = work.loc[work["n_apps"] >= int(min_apps)].copy()
    if work.empty:
        st.info("No edges left after filters (min weight / self-loops).")
        return

    work = work.sort_values("n_apps", ascending=False).head(int(top_k)).copy()

    raw_nodes = sorted({int(x) for x in set(work["from_stage"]).union(set(work["to_stage"]))})
    full_labels = [stage_label.get(int(s), f"Stage {int(s)}") for s in raw_nodes]

    def _compact_label(s: str, *, max_len: int) -> str:
        # Labels look like: "04 · Ops queue · account manager assigned"
        # Keep the step + first meaningful bucket for readability.
        parts = [p.strip() for p in s.split("·")]
        if len(parts) >= 2:
            head = f"{parts[0]} · {parts[1]}"
            # Trim common verbose tails like "(...)" unless it's the primary token.
            out = head.strip()
        else:
            out = s.strip()
        if len(out) > max_len:
            return out[: max_len - 1] + "…"
        return out

    # Always keep hover text full; only shorten on-canvas labels when requested.
    max_canvas = 34 if compact_node_labels else 52
    labels = [_compact_label(s, max_len=max_canvas) for s in full_labels]

    # Order nodes by stage id (process order) to reduce crossing / label pile-ups.
    nodes = list(raw_nodes)
    node_index = {int(s): i for i, s in enumerate(nodes)}

    # More nodes => more vertical space needed to avoid label collisions.
    height = int(max(620, min(1200, 360 + 40 * len(nodes))))

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="perpendicular",
                node=dict(
                    pad=18,
                    thickness=18,
                    line=dict(width=0.5, color="#cfd4dc"),
                    label=labels,
                    customdata=full_labels,
                    hovertemplate="%{customdata}<extra></extra>",
                ),
                link=dict(
                    source=[node_index[int(s)] for s in work["from_stage"].tolist()],
                    target=[node_index[int(s)] for s in work["to_stage"].tolist()],
                    value=[int(v) for v in work["n_apps"].tolist()],
                    hovertemplate=(
                        "<b>%{source.customdata}</b> → <b>%{target.customdata}</b><br>"
                        "%{value} apps<extra></extra>"
                    ),
                ),
            )
        ]
    )
    fig.update_layout(
        margin=dict(l=22, r=22, t=34, b=22),
        height=height,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(size=15, family="system-ui, -apple-system, Segoe UI, Arial, sans-serif", color="#111"),
    )
    st.plotly_chart(fig, use_container_width=True)


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


def _cohort_application_ids(
    qm: QueryManager, *, product_type: str | None, date_range: tuple[str, str]
) -> list[str]:
    df = qm.run_sql(
        """
        SELECT DISTINCT application_id
        FROM audit_logs
        WHERE {{PRODUCT_TYPE_FILTER}} AND {{DATE_RANGE_FILTER}}
        ORDER BY 1
        """,
        product_type=product_type,
        date_range=date_range,
    )
    return [str(x) for x in df["application_id"].tolist()] if not df.empty else []


def _transitions_with_actor(
    qm: QueryManager,
    *,
    product_type: str | None,
    date_range: tuple[str, str],
) -> pd.DataFrame:
    # Attribution rule: actor who triggered the to_stage event (audit_logs row at transition timestamp).
    return qm.run_sql(
        """
        WITH cohort AS (
            SELECT DISTINCT application_id
            FROM audit_logs
            WHERE {{PRODUCT_TYPE_FILTER}} AND {{DATE_RANGE_FILTER}}
        ),
        raw AS (
            SELECT
                t.application_id,
                t.from_stage,
                t.to_stage,
                t.transition_at,
                t.reason
            FROM v_transitions AS t
            INNER JOIN cohort AS c ON c.application_id = t.application_id
            WHERE t.transition_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
        )
        SELECT
            r.application_id,
            r.from_stage,
            r.to_stage,
            r.transition_at,
            a.actor,
            COALESCE(vt.team, 'Other') AS team
        FROM raw AS r
        LEFT JOIN audit_logs AS a
          ON a.application_id = r.application_id
         AND a.timestamp = r.transition_at
         AND a.action = r.reason
        LEFT JOIN v_team AS vt
          ON vt.application_id = a.application_id
         AND vt.timestamp = a.timestamp
         AND vt.action = r.reason
         AND vt.actor = a.actor
        WHERE COALESCE(vt.team, 'Other') IN ('CR', 'Compliance');
        """,
        product_type=product_type,
        date_range=date_range,
    )


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
        .mark_circle(opacity=0.85)
        .encode(
            x=alt.X("completed_7d:Q", title="Completed last 7 days"),
            y=alt.Y("open_cases_now:Q", title="Open cases now"),
            size=alt.Size("completed_30d:Q", title="Completed last 30 days", legend=None),
            color=alt.Color("team:N", title="Team"),
            shape=alt.Shape("suggested_rebalance_flag:N", title="Needs attention"),
            tooltip=[
                "actor_label",
                "open_cases_now",
                "completed_7d",
                "completed_30d",
                alt.Tooltip("p90_age_open_days:Q", format=".1f", title="P90 open age days"),
            ],
        )
        .properties(height=320)
    )
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


def main() -> None:
    st.set_page_config(page_title="Relio Operations Intelligence", layout="wide")
    st.title("Relio Operations Intelligence")

    db_rel = st.sidebar.text_input(
        "DuckDB path (relative to project)",
        value="data/relio_analytics.db",
    )
    db_path = Path(db_rel)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    if not db_path.is_file():
        try:
            with st.spinner("First boot: generating demo dataset + DuckDB (may take ~30–90s on Cloud)…"):
                _bootstrap_demo_duckdb(repo_root=PROJECT_ROOT, db_path=db_path)
            st.success(f"Created demo database at `{db_path}`")
        except Exception as e:  # noqa: BLE001
            st.error(
                "Could not auto-create the DuckDB file. "
                "For local dev, run `python3 scripts/generate_synthetic_audit_log.py` then `python3 scripts/db_setup.py`."
            )
            st.exception(e)
            st.stop()

    db_mtime_ns = db_path.stat().st_mtime_ns if db_path.exists() else 0
    try:
        con = _connect_readonly(db_path, db_mtime_ns=db_mtime_ns)
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    qm = QueryManager(con)

    st.sidebar.header("Filters")
    product_choices = _sidebar_product_options(con)
    product_choice = st.sidebar.selectbox("Product type", product_choices)
    product_filter = _parse_product_filter(product_choice)

    min_d, max_d = _sidebar_date_bounds(con)
    e2e_dr = os.environ.get("RELIO_E2E_DATE_RANGE", "").strip()
    if e2e_dr and "," in e2e_dr:
        try:
            a, b = [s.strip() for s in e2e_dr.split(",", 1)]
            default_dr = (pd.to_datetime(a).date(), pd.to_datetime(b).date())
        except Exception:  # noqa: BLE001
            default_dr = (min_d, max_d)
    else:
        # Demo-friendly default: a recent window ending at the max date.
        # Picking min→max makes period start snapshot trivially collapse to step 0 (no prior history).
        lookback_days = 21
        try:
            start_d = max(min_d, (pd.to_datetime(max_d) - pd.Timedelta(days=lookback_days)).date())
        except Exception:  # noqa: BLE001
            start_d = min_d
        default_dr = (start_d, max_d)
    dr = st.sidebar.date_input(
        "Date range",
        value=default_dr,
        min_value=min_d,
        max_value=max_d,
    )
    if isinstance(dr, tuple) and len(dr) == 2:
        date_range = (str(dr[0]), str(dr[1]))
    elif hasattr(dr, "isoformat"):
        ds = dr.isoformat()[:10]
        date_range = (ds, ds)
    else:
        date_range = None

    tab_overview, tab_period, tab_bottleneck, tab_rework, tab_team, tab_sla, tab_capacity, tab_cohort, tab_investigate = st.tabs(
        [
            "Executive overview",
            "Period dashboard",
            "Bottleneck radar",
            "Rework analytics",
            "Team workload",
            "SLA compliance",
            "Capacity what-if",
            "Cohort analytics",
            "App investigator",
        ]
    )

    with tab_overview:
        st.header("Executive overview")

        denom_df = qm.run_sql(KPI_DENOM_SQL, product_type=product_filter, date_range=date_range)
        denom = int(denom_df.iloc[0]["n"]) if len(denom_df) else 0

        active_df = qm.run_sql(KPI_ACTIVE_SQL, product_type=product_filter, date_range=date_range)
        n_active = int(active_df.iloc[0]["n"]) if len(active_df) else 0

        avg_df = qm.run_sql(KPI_AVG_PROCESSING_SQL, product_type=product_filter, date_range=date_range)
        avg_days = float(avg_df.iloc[0]["avg_days"]) if len(avg_df) and avg_df.iloc[0]["avg_days"] is not None else 0.0

        stuck_df = qm.run(
            "stuck_applications",
            product_type=product_filter,
            date_range=date_range,
        )
        n_stuck = stuck_df["application_id"].nunique() if len(stuck_df) else 0
        pct_stuck = (100.0 * n_stuck / denom) if denom else 0.0

        k0, k1, k2, k3 = st.columns(4)
        k0.metric(
            "In filter (cohort)",
            f"{denom:,}",
            help="Applications that have at least one audit row in the selected product and date range.",
        )
        k1.metric(
            "In-flight (not finished)",
            f"{n_active:,}",
            help="Same cohort, but latest event is not a terminal outcome (e.g. not master data submitted).",
        )
        k2.metric("Avg. processing time (days)", f"{avg_days:.1f}")
        k3.metric("% stuck > 48h (in-flight)", f"{pct_stuck:.1f}%")

        thr = (
            qm.run("throughput_daily", product_type=product_filter, date_range=date_range)
            if date_range is not None
            else pd.DataFrame()
        )
        thr_7d = int(thr.tail(7)["n_terminated"].sum()) if len(thr) else 0
        thr_ma7 = float(thr.tail(1)["n_terminated_ma7"].iloc[0]) if len(thr) else 0.0

        sla = qm.run(
            "sla_breach_overview",
            product_type=product_filter,
            date_range=date_range,
        )
        def _sla_n(area: str, status: str) -> int:
            if sla.empty:
                return 0
            m = (sla["sla_area"] == area) & (sla["status"] == status)
            return int(sla.loc[m, "n_applications"].sum()) if m.any() else 0

        s0, s1, s2, s3 = st.columns(4)
        s0.metric("Throughput (terminal) last 7d", f"{thr_7d:,}")
        s1.metric("Throughput MA7 (per day)", f"{thr_ma7:.1f}")
        s2.metric("CR breached (as of now)", f"{_sla_n('CR review', 'breached'):,}")
        s3.metric("Compliance breached (as of now)", f"{_sla_n('Compliance', 'breached'):,}")

        with st.expander("KPI definitions (PHASE_0 §5)", expanded=False):
            st.caption(legend_subtitle("kpi_in_filter"))
            st.caption(legend_subtitle("kpi_in_flight"))
            st.caption(legend_subtitle("kpi_avg_processing"))
            st.caption(legend_subtitle("kpi_pct_stuck"))
            st.caption(legend_subtitle("throughput_daily"))
            st.caption(legend_subtitle("sla_breach_overview"))

        st.subheader("Latest stage per application — swimlanes (snapshot)")
        st.caption(legend_subtitle("funnel_swimlanes"))
        swim = qm.run(
            "funnel_swimlanes",
            product_type=product_filter,
            date_range=date_range,
        )
        swim_total = int(swim["active_applications"].sum()) if len(swim) else 0
        st.caption(
            f"{legend_subtitle('funnel_bar_sum')} "
            f"Current sum: **{swim_total:,}** vs in-filter **{denom:,}**."
        )
        _swimlane_chart(swim)

        c_l, c_r = st.columns([1, 1])
        with c_l:
            st.subheader("Who has the ball (in-flight)")
            st.caption(legend_subtitle("who_has_the_ball"))
            ball = qm.run(
                "who_has_the_ball",
                product_type=product_filter,
                date_range=date_range,
            )
            if ball.empty:
                st.info("No in-flight applications in this filter.")
            else:
                _who_has_ball_chart(ball)
        with c_r:
            st.subheader("SLA status (in-flight)")
            st.caption(legend_subtitle("sla_breach_overview"))
            if sla.empty:
                st.info("No in-flight applications in this filter.")
            else:
                st.dataframe(sla, hide_index=True, width="stretch")

        with st.expander("Drill-down: latest stage per application (34 steps)", expanded=False):
            st.caption(legend_subtitle("funnel_latest_stage"))
            funnel_df = qm.run(
                "funnel_overview",
                product_type=product_filter,
                date_range=date_range,
            )
            bar_total = int(funnel_df["active_applications"].sum())
            st.caption(
                f"{legend_subtitle('funnel_bar_sum')} "
                f"Current sum: **{bar_total:,}** vs in-filter **{denom:,}**."
            )
            _funnel_chart(funnel_df)

        st.subheader("Watchlist — stuck > 48h (oldest first, top 10)")
        st.caption(legend_subtitle("watchlist_stuck"))
        watch = stuck_df.head(10).copy()
        if watch.empty:
            st.info("No stuck applications in this filter.")
        else:
            # Enrich with team + days in current stage (derived from latest event).
            enrich = qm.run(
                "who_has_the_ball",
                product_type=product_filter,
                date_range=date_range,
            )
            # who_has_the_ball is aggregated; we need per-app info via SQL quickly.
            per_app = qm.run_sql(
                """
                WITH latest AS (
                    SELECT
                        a.application_id,
                        arg_max(t.team, a.timestamp) AS team,
                        arg_max(a.timestamp, a.timestamp) AS last_ts
                    FROM audit_logs AS a
                    LEFT JOIN v_team AS t
                      ON t.application_id = a.application_id
                     AND t.timestamp = a.timestamp
                     AND t.action = a.action
                     AND t.actor = a.actor
                    WHERE {{PRODUCT_TYPE_FILTER}}
                    GROUP BY a.application_id
                ),
                cur AS (
                    SELECT
                        d.application_id,
                        d.entered_at,
                        d.is_open
                    FROM v_stage_dwell AS d
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY d.application_id
                        ORDER BY d.entered_at DESC
                    ) = 1
                )
                SELECT
                    l.application_id,
                    COALESCE(l.team, 'Other') AS waiting_on,
                    (EXTRACT(EPOCH FROM (current_timestamp - c.entered_at)) / 86400.0) AS days_in_current_stage
                FROM latest AS l
                LEFT JOIN cur AS c USING (application_id)
                """,
                product_type=product_filter,
                date_range=None,
            )
            if not per_app.empty:
                watch = watch.merge(per_app, on="application_id", how="left")
            st.dataframe(
                watch,
                hide_index=True,
                width="stretch",
                column_config={
                    "application_id": TextColumn(
                        "Application ID",
                        width="large",
                        help="Primary entity key — paste into App investigator.",
                    ),
                    "case_owner": TextColumn(
                        "Case owner (Relio)",
                        width="medium",
                        help="Internal owner for follow-up; not always the same as latest actor.",
                    ),
                    "latest_actor": TextColumn("Latest actor"),
                    "current_action": TextColumn("Current action"),
                    "latest_at": DatetimeColumn("Latest event", format="YYYY-MM-DD HH:mm"),
                    "waiting_on": TextColumn("Waiting on"),
                    "days_in_current_stage": TextColumn("Days in current stage"),
                },
            )

    with tab_investigate:
        st.header("App investigator")
        st.caption(
            "Repeat rows for compliance / interaction actions are highlighted when the same action "
            "fires more than once (review loops)."
        )

        inv_id = st.text_input(
            "Investigate application ID",
            placeholder="Paste UUID from watchlist or funnel exports",
            key="investigate_app_id",
        ).strip()

        if inv_id:
            hist = qm.run(
                "application_history",
                product_type=product_filter,
                application_id=inv_id,
            )
            if hist.empty:
                st.warning(
                    "No rows returned. Check the ID and product filter "
                    "(full history ignores the sidebar date range)."
                )
            else:
                st.subheader("Audit timeline")
                loop_mask = _history_loop_flags(hist)
                display_cols = ["timestamp", "actor", "action", "description", "context"]
                table_df = hist[display_cols].copy()
                components.html(
                    _history_html_table(table_df, loop_mask),
                    height=min(760, 120 + len(table_df) * 36),
                    scrolling=True,
                )
                st.caption("Pink rows: repeated review / interaction actions (operational loops).")

                dwell = qm.run_sql(
                    """
                    WITH cur AS (
                        SELECT *
                        FROM v_stage_dwell
                        WHERE application_id = {{APP_ID_FILTER}}
                          AND {{PRODUCT_TYPE_FILTER}}
                        ORDER BY entered_at
                    ),
                    dim AS (
                        SELECT * FROM (VALUES
                            (1, '01 · INITIAL (application started)'),
                            (2, '02 · SUBMITTED (application submitted)'),
                            (3, '03 · DOCUMENTS_UPLOAD (docs submitted)'),
                            (4, '04 · Ops queue · account manager assigned'),
                            (5, '05 · Ops queue · app assigned'),
                            (6, '06 · REVIEW · CR review started'),
                            (7, '07 · REVIEW · CR review completed'),
                            (8, '08 · REVIEW · compliance review started'),
                            (9, '09 · INTERACTION_SUMMARY (RFI sent)'),
                            (10, '10 · INTERACTION_SUBMITTED'),
                            (11, '11 · INTERACTION_CANCELLED (CR interaction cancelled)'),
                            (12, '12 · CR interaction started'),
                            (13, '13 · INTERACTION_EDIT · answers edit started'),
                            (14, '14 · INTERACTION_EDIT · answers edit finished'),
                            (15, '15 · REVIEW · label added'),
                            (16, '16 · REVIEW · compliance review completed'),
                            (17, '17 · REJECTED (application rejected)'),
                            (18, '18 · CANCELLED (application cancelled)'),
                            (19, '19 · APPROVED path · offer prepared'),
                            (20, '20 · OFFER_SENT'),
                            (21, '21 · OFFER_RESPONSE (acceptOffer)'),
                            (22, '22 · OFFER_REFUSED'),
                            (23, '23 · Post-accept · video ident sent'),
                            (24, '24 · Post-accept · video ident finished'),
                            (25, '25 · Post-accept · enrollment approved'),
                            (26, '26 · Post-accept · master data submitted'),
                            (34, '34 · Other / unknown action')
                        ) AS t(stage_order, stage_label)
                    )
                    SELECT
                        c.entered_at,
                        c.exited_at,
                        c.stage_order,
                        d.stage_label,
                        COALESCE(c.dwell_hours, EXTRACT(EPOCH FROM (current_timestamp - c.entered_at)) / 3600.0) AS dwell_hours
                    FROM cur AS c
                    LEFT JOIN dim AS d ON c.stage_order = d.stage_order
                    ORDER BY c.entered_at
                    """,
                    product_type=product_filter,
                    application_id=inv_id,
                    date_range=None,
                )
                if not dwell.empty:
                    st.subheader("Time in stage (hours)")
                    dplot = dwell.copy()
                    dplot["stage_label"] = dplot["stage_label"].fillna(dplot["stage_order"].astype(str))
                    c = (
                        alt.Chart(dplot)
                        .mark_bar()
                        .encode(
                            x=alt.X("dwell_hours:Q", title="Hours"),
                            y=alt.Y("stage_label:N", sort=None, title="Stage"),
                            tooltip=[
                                "stage_label",
                                alt.Tooltip("dwell_hours:Q", format=".1f", title="Hours"),
                            ],
                        )
                        .properties(height=min(520, max(200, 22 * len(dplot))))
                    )
                    st.altair_chart(c, width="stretch")
        else:
            st.info("Enter an application UUID to load its audit trail.")

    with tab_cohort:
        st.header("Cohort analytics")
        anchor_labels = {
            "submitted": "Submitted — first APPLICATION_SUBMITTED",
            "enrollment": "Enrollment — first ENROLLMENT_APPROVED",
            "assigned": "First assigned — earliest APP_ASSIGNED / ACCOUNT_MANAGER_ASSIGNED",
            "compliance": "First compliance — COMPLIANCE_REVIEW_STARTED",
        }
        anchor_kind = st.selectbox(
            "Cohort anchor (§4)",
            options=list(anchor_labels.keys()),
            format_func=lambda k: anchor_labels[k],
            key="cohort_anchor",
        )
        as_of_input = st.date_input(
            "As-of date (naive calendar day)",
            value=max_d,
            min_value=min_d,
            max_value=max_d,
            key="cohort_as_of",
        )
        as_of_s = as_of_input.isoformat()[:10] if hasattr(as_of_input, "isoformat") else str(as_of_input)[:10]

        excl = qm.run(
            "cohort_anchor_excluded",
            product_type=product_filter,
            date_range=None,
            anchor_kind=anchor_kind,
        )
        n_ex = int(excl.iloc[0]["n_excluded_no_anchor"]) if len(excl) else 0
        st.caption(
            f"{legend_subtitle('cohort_anchor_excluded')} **Excluded (no anchor): {n_ex:,}** applications."
        )

        st.subheader("Single KPI")
        single_kpi_labels = {
            "in_flight": "In-flight % (as-of date)",
            "survival": "Survival % at +N days (as-of date)",
            "time_to_offer": "Time to first offer (days) — p50 / p90",
        }
        single_kpi = st.selectbox(
            "Metric",
            options=list(single_kpi_labels.keys()),
            format_func=lambda k: single_kpi_labels[k],
            key="cohort_single_kpi_choice",
        )

        if single_kpi == "in_flight":
            st.caption(legend_subtitle("cohort_single_kpi"))
            kpi_df = qm.run(
                "cohort_single_kpi",
                product_type=product_filter,
                date_range=None,
                as_of_date=as_of_s,
                anchor_kind=anchor_kind,
            )
            if kpi_df.empty:
                st.info("No cohort rows for this anchor and as-of date.")
            else:
                st.dataframe(kpi_df, hide_index=True, width="stretch")
        elif single_kpi == "survival":
            horizon = st.selectbox(
                "Horizon",
                options=[7, 14, 30, 60],
                format_func=lambda d: f"+{d} days",
                key="cohort_survival_horizon",
            )
            surv = qm.run(
                "cohort_survival",
                product_type=product_filter,
                date_range=None,
                as_of_date=as_of_s,
                anchor_kind=anchor_kind,
            )
            if surv.empty:
                st.info("No survival rows for this anchor/as-of date.")
            else:
                col = f"pct_alive_{horizon}d"
                show = surv[["cohort_month", "n_apps", col]].rename(columns={col: "pct_alive"})
                st.dataframe(show, hide_index=True, width="stretch")
        else:
            tto = qm.run(
                "cohort_time_to_offer",
                product_type=product_filter,
                date_range=None,
                as_of_date=as_of_s,
                anchor_kind=anchor_kind,
            )
            if tto.empty:
                st.info("No offer rows for this anchor/as-of date.")
            else:
                st.dataframe(tto, hide_index=True, width="stretch")

        st.subheader("Multi-KPI (combined table)")
        multi = qm.run(
            "cohort_multi_kpi",
            product_type=product_filter,
            date_range=None,
            as_of_date=as_of_s,
            anchor_kind=anchor_kind,
        )
        if multi.empty:
            st.info("No cohort rows for this anchor and as-of date.")
        else:
            st.dataframe(multi, hide_index=True, width="stretch")

        st.subheader("Stage mix (as-of date)")
        st.caption(legend_subtitle("cohort_status_snapshot"))
        snap = qm.run(
            "cohort_status_snapshot",
            product_type=product_filter,
            date_range=None,
            as_of_date=as_of_s,
            anchor_kind=anchor_kind,
        )
        if snap.empty:
            st.info("No rows for stage mix snapshot.")
        else:
            pivot = snap.pivot_table(
                index="cohort_month",
                columns="step_order",
                values="n_applications",
                aggfunc="sum",
                fill_value=0,
            )
            st.dataframe(pivot, width="stretch")

    with tab_period:
        st.header("Period dashboard")
        with st.expander("Prior-period compare (optional)", expanded=False):
            st.caption(
                "Reuse the same period queries with a shifted sidebar date_range; no separate endpoint yet "
                "(PHASE_0 §2, RUNBOOK.md)."
            )
        st.caption(
            f"Reporting window: **{date_range[0]}** → **{date_range[1]}** (inclusive, naive dates · PHASE_0 §2)."
            if date_range
            else "Select a date range in the sidebar to anchor period metrics."
        )
        if date_range is None:
            st.warning("Period SQL requires both start and end dates.")
        else:
            pd_board = load_period_dashboard(qm, product_type=product_filter, date_range=date_range)
            cohort_n = int(pd_board.end_snapshot["active_applications"].sum())
            start_term = int(
                pd_board.start_snapshot.loc[
                    pd_board.start_snapshot["step_order"].isin(TERMINAL_STEP_ORDERS),
                    "active_applications",
                ].sum()
            )
            end_term = int(
                pd_board.end_snapshot.loc[
                    pd_board.end_snapshot["step_order"].isin(TERMINAL_STEP_ORDERS),
                    "active_applications",
                ].sum()
            )

            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            r1c1.metric(
                "Cohort (in period)",
                f"{cohort_n:,}",
                help="Distinct applications with ≥1 audit row in the filter window + product (§5 In filter).",
            )
            r1c2.metric("Arrivals (first touch in window)", f"{pd_board.n_arrivals:,}")
            r1c3.metric("Losses (terminal event in window)", f"{pd_board.n_losses:,}")
            r1c4.metric("Movers (≥1 logical move)", f"{pd_board.n_movers:,}")

            r2c1, r2c2, r2c3 = st.columns(3)
            r2c1.metric(
                "Apps in terminal stage (start snapshot)",
                f"{start_term:,}",
                help="Count in funnel buckets 17/18/22/26 at start-of-period snapshot.",
            )
            r2c2.metric("Apps in terminal stage (end snapshot)", f"{end_term:,}")
            r2c3.metric("Δ terminal bucket (end − start)", f"{end_term - start_term:,}")

            st.subheader("Start snapshot — stage mix")
            st.caption(legend_subtitle("period_start_snapshot"))
            with st.expander("What is this showing?", expanded=False):
                st.markdown(
                    """
This is a **baseline** for the reporting window.

- **Cohort**: applications that have **≥1 audit event during the selected window** \([start, end]\).
- **Snapshot moment**: the app’s **latest known stage strictly before the start day**.
- **Step 0 (“no audit before period start”)**: apps in the cohort that had **no history before the window** — effectively *new arrivals relative to this window*.

Why it matters: it tells you whether in-window movement is mostly **work already in progress** (carryover) vs **new inflow** (step 0).

Mini example:

- Window = **Apr 10 → Apr 20**
- App A had events before Apr 10 → it appears in its last pre-window stage (e.g. “08 · compliance started”)
- App B’s first-ever event is Apr 12 → it appears as **00 · (no audit before period start)** in the start snapshot
                    """.strip()
                )
            start_plot = pd_board.start_snapshot.query("active_applications > 0").copy()
            if start_plot.empty:
                st.info("No cohort rows in this window for the current filters.")
            else:
                nonzero_nonpre = int(
                    start_plot.loc[start_plot["step_order"] != 0, "active_applications"].sum()
                )
                st.metric(
                    "Start snapshot — apps with prior history (step_order ≠ 0)",
                    f"{nonzero_nonpre:,}",
                    help=(
                        "Sanity check for demos: cohort apps whose last known stage is not the "
                        "synthetic step 0 (no audit before period start)."
                    ),
                )
                if nonzero_nonpre == 0:
                    st.warning(
                        "Start snapshot is fully collapsed to step_order=0 (no prior history for any cohort app). "
                        "For synthetic demos this usually means the DB was generated without carryover history, "
                        "or the selected period starts before any prefixed history exists."
                    )
                _funnel_chart(start_plot)

            st.subheader("End snapshot — stage mix")
            st.caption(legend_subtitle("period_end_snapshot"))
            end_plot = pd_board.end_snapshot.query("active_applications > 0").copy()
            if end_plot.empty:
                st.info("No cohort rows for end snapshot with the current filters.")
            else:
                _funnel_chart(end_plot)

            st.subheader("In-period transition flow")
            st.caption(legend_subtitle("period_transition_matrix"))
            st.caption(legend_subtitle("period_arrivals_losses"))
            edges = pd_board.transition_edges.copy()
            if edges.empty:
                st.info("No logical transitions with transition_at inside the window for this cohort.")
            else:
                lab = pd_board.end_snapshot[["step_order", "step_label"]].drop_duplicates()
                mlab = lab.set_index("step_order")["step_label"].to_dict()
                edges["from_label"] = edges["from_stage"].map(mlab).fillna("?")
                edges["to_label"] = edges["to_stage"].map(mlab).fillna("?")

                left, right = st.columns([1, 1])
                with left:
                    top_k = int(
                        st.slider(
                            "Top edges to display",
                            min_value=10,
                            max_value=80,
                            value=35,
                            step=5,
                        )
                    )
                    min_apps = int(
                        st.slider(
                            "Min apps per edge",
                            min_value=1,
                            max_value=250,
                            value=10,
                            step=1,
                        )
                    )
                with right:
                    include_self = bool(st.checkbox("Include self-loops", value=False))
                    compact_labels = bool(
                        st.checkbox("Compact node labels", value=True, help="Shorten stage labels on the chart; full labels show on hover.")
                    )
                    st.caption(
                        "Tip: raise the min threshold or lower top-K to reduce visual noise."
                    )

                _transition_sankey(
                    edges,
                    stage_label=mlab,
                    top_k=top_k,
                    min_apps=min_apps,
                    include_self_loops=include_self,
                    compact_node_labels=compact_labels,
                )

                with st.expander("Show transition edges as a table", expanded=False):
                    show = edges[
                        ["from_label", "from_stage", "to_label", "to_stage", "n_apps"]
                    ].sort_values("n_apps", ascending=False)
                    st.dataframe(show, hide_index=True, width="stretch")

    with tab_bottleneck:
        st.header("Bottleneck radar")
        st.caption(
            "Rank stages by where WIP and aging are accumulating (operational bottleneck signal)."
        )
        if date_range is None:
            st.warning("Select a date range in the sidebar to anchor bottleneck metrics.")
        else:
            radar = qm.run(
                "bottleneck_radar",
                product_type=product_filter,
                date_range=date_range,
            )
            if radar.empty:
                st.info("No rows for this filter.")
            else:
                st.dataframe(radar, hide_index=True, width="stretch")

    with tab_rework:
        st.header("Rework analytics")
        st.caption(
            "Quantify interaction loops and reopened compliance to target process fixes."
        )
        if date_range is None:
            st.warning("Select a date range in the sidebar to anchor rework metrics.")
        else:
            overall = qm.run(
                "rework_overview",
                product_type=product_filter,
                date_range=date_range,
            )
            by_prod = qm.run(
                "rework_by_product",
                product_type=product_filter,
                date_range=date_range,
            )
            if overall.empty:
                st.info("No rows for this filter.")
            else:
                st.dataframe(overall, hide_index=True, width="stretch")
            if not by_prod.empty:
                st.subheader("By product type")
                st.dataframe(by_prod, hide_index=True, width="stretch")

    with tab_team:
        st.header("Team workload")
        st.caption("Per-actor workload view for CR and Compliance.")
        if date_range is None:
            st.warning("Select a date range in the sidebar to anchor workload metrics.")
        else:
            wl = qm.run(
                "team_workload",
                product_type=product_filter,
                date_range=date_range,
            )
            if wl.empty:
                st.info("No workload rows for this filter.")
            else:
                wl = wl.copy()
                for col in ["open_cases_now", "completed_7d", "completed_30d", "p90_age_open_days"]:
                    wl[col] = pd.to_numeric(wl[col], errors="coerce").fillna(0)
                wl["suggested_rebalance_flag"] = wl["suggested_rebalance_flag"].fillna(False).astype(bool)

                cr_open = int(wl.loc[wl["team"] == "CR", "open_cases_now"].sum())
                comp_open = int(wl.loc[wl["team"] == "Compliance", "open_cases_now"].sum())
                attention = _team_workload_exceptions(wl)
                max_age = float(wl["p90_age_open_days"].max()) if len(wl) else 0.0
                active_actors = int((wl["open_cases_now"] > 0).sum())

                k0, k1, k2, k3 = st.columns(4)
                k0.metric("CR open cases", f"{cr_open:,}")
                k1.metric("Compliance open cases", f"{comp_open:,}")
                k2.metric("Actors with open work", f"{active_actors:,}")
                k3.metric("Max p90 open age", f"{max_age:.1f}d")

                st.subheader("Open workload by actor")
                left, right = st.columns(2)
                with left:
                    st.markdown("**CR**")
                    _team_open_cases_chart(wl, team="CR")
                with right:
                    st.markdown("**Compliance**")
                    _team_open_cases_chart(wl, team="Compliance")

                st.subheader("Throughput vs backlog")
                st.caption(
                    "Each point is an actor. Higher means more open backlog; farther right means more cases completed in the last 7 days."
                )
                _team_backlog_throughput_chart(wl)

                st.subheader("Attention list")
                if attention.empty:
                    st.success("No actors crossed the current attention thresholds.")
                else:
                    st.dataframe(
                        attention,
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "team": TextColumn("Team"),
                            "actor": TextColumn("Actor", width="large"),
                            "open_cases_now": st.column_config.NumberColumn("Open cases", format="%d"),
                            "completed_7d": st.column_config.NumberColumn("Completed 7d", format="%d"),
                            "completed_30d": st.column_config.NumberColumn("Completed 30d", format="%d"),
                            "p90_age_open_days": st.column_config.NumberColumn("P90 open age", format="%.1f days"),
                            "reason": TextColumn("Why this is shown", width="large"),
                        },
                    )

                st.subheader("Capacity calendars")
                st.caption(
                    "Mock staffing inputs today. Edit weekly allocation per person, then use the monthly calendars to see effective people by day."
                )

                start_day, end_day = _date_range_days(date_range)
                # Use a fixed roster size (8 each) for capacity modeling.
                roster_cr = generate_team_roster("CR", n_people=8)
                roster_comp = generate_team_roster("Compliance", n_people=8)

                # Staffing calendars (editable, stored in session state per filter window).
                cal_key = f"staffing_calendar::{start_day}::{end_day}::{product_filter or '(All)'}"
                if cal_key not in st.session_state:
                    cal_cr = generate_staffing_calendar(
                        actors=roster_cr,
                        team="CR",
                        start_day=start_day,
                        end_day=end_day,
                        seed=42,
                    )
                    cal_comp = generate_staffing_calendar(
                        actors=roster_comp,
                        team="Compliance",
                        start_day=start_day,
                        end_day=end_day,
                        seed=42,
                    )
                    st.session_state[cal_key] = pd.concat([cal_cr, cal_comp], ignore_index=True)

                staffing = st.session_state[cal_key].copy()

                st.markdown("**Capacity calendar** (edit % allocation per person per day)")
                availability_options = [0, 25, 50, 75, 100]
                staffing["day"] = staffing["day"].astype(str)
                days_all = pd.to_datetime(staffing["day"]).dt.date
                min_day = days_all.min()
                max_day = days_all.max()
                if min_day is None or max_day is None:
                    st.info("No staffing days available for this window.")
                else:
                    # Week selector (keeps the calendar manageable for long windows).
                    week_start_default = min_day
                    week_start = st.date_input(
                        "Week starting",
                        value=week_start_default,
                        min_value=min_day,
                        max_value=max_day,
                        key=f"{cal_key}::week_start",
                    )
                    week_days = [
                        (pd.Timestamp(week_start) + pd.Timedelta(days=i)).date().isoformat()
                        for i in range(7)
                    ]
                    week_days = [d for d in week_days if min_day.isoformat() <= d <= max_day.isoformat()]

                    team_choice = st.radio(
                        "Team",
                        options=["CR", "Compliance"],
                        horizontal=True,
                        key=f"{cal_key}::team_choice",
                    )
                    week = staffing.query("team == @team_choice and day in @week_days").copy()
                    if week.empty:
                        st.info("No rows for this team/week (outside staffing window).")
                    else:
                        pivot = (
                            week.pivot_table(
                                index="actor",
                                columns="day",
                                values="availability_pct",
                                aggfunc="first",
                                fill_value=0,
                            )
                            .reindex(columns=week_days, fill_value=0)
                            .reset_index()
                        )
                        edited_pivot = st.data_editor(
                            pivot,
                            hide_index=True,
                            width="stretch",
                            column_config={
                                d: st.column_config.SelectboxColumn(
                                    d,
                                    options=availability_options,
                                    required=True,
                                )
                                for d in week_days
                            },
                            key=f"{cal_key}::calendar::{team_choice}::{week_start.isoformat()}",
                        )
                        # Write edits back to long format.
                        melted = edited_pivot.melt(
                            id_vars=["actor"],
                            value_vars=week_days,
                            var_name="day",
                            value_name="availability_pct",
                        )
                        staffing = staffing.merge(
                            melted.assign(team=team_choice),
                            on=["team", "actor", "day"],
                            how="left",
                            suffixes=("", "_new"),
                        )
                        staffing["availability_pct"] = staffing["availability_pct_new"].fillna(
                            staffing["availability_pct"]
                        )
                        staffing = staffing.drop(columns=["availability_pct_new"])

                st.session_state[cal_key] = staffing

                daily_cap = (
                    staffing.groupby(["team", "day"], as_index=False)
                    .agg(
                        effective_people=("availability_pct", lambda s: float(s.sum()) / 100.0),
                        headcount_working=("availability_pct", lambda s: int((s.astype(int) > 0).sum())),
                    )
                    .sort_values(["team", "day"])
                )

                eff_by_team = daily_cap.groupby("team")["effective_people"].sum().to_dict()
                c0, c1, c2 = st.columns(3)
                c0.metric("CR effective team-days", f"{float(eff_by_team.get('CR', 0.0)):.1f}")
                c1.metric(
                    "Compliance effective team-days",
                    f"{float(eff_by_team.get('Compliance', 0.0)):.1f}",
                )
                c2.metric("Total effective team-days", f"{float(sum(eff_by_team.values())):.1f}")

                st.markdown("**Calendar view** (Sat/Sun shaded)")
                # Month selector based on the staffing window.
                month_min = pd.to_datetime(start_day).to_period("M").to_timestamp().date()
                month_max = pd.to_datetime(end_day).to_period("M").to_timestamp().date()
                month_choice = st.date_input(
                    "Month",
                    value=month_min,
                    min_value=month_min,
                    max_value=month_max,
                    key=f"{cal_key}::month_choice",
                )
                y = int(month_choice.year)
                m = int(month_choice.month)
                lcal, rcal = st.columns(2)
                with lcal:
                    components.html(
                        _capacity_calendar_html(
                            daily_cap.query("team == 'CR'")[["day", "effective_people", "headcount_working"]],
                            team="CR",
                            year=y,
                            month=m,
                        ),
                        height=520,
                    )
                with rcal:
                    components.html(
                        _capacity_calendar_html(
                            daily_cap.query("team == 'Compliance'")[["day", "effective_people", "headcount_working"]],
                            team="Compliance",
                            year=y,
                            month=m,
                        ),
                        height=520,
                    )

    with tab_sla:
        st.header("SLA compliance")
        st.caption(
            "SLA adherence for key steps (v0 thresholds in SQL). Use as an internal control view."
        )
        if date_range is None:
            st.warning("Select a date range in the sidebar to anchor SLA metrics.")
        else:
            sla = qm.run(
                "sla_compliance",
                product_type=product_filter,
                date_range=date_range,
            )
            trend = qm.run(
                "sla_compliance_trend",
                product_type=product_filter,
                date_range=date_range,
            )
            if sla.empty:
                st.info("No eligible SLA rows for this filter.")
            else:
                tiles = st.columns(min(4, len(sla)))
                for i, (_, row) in enumerate(sla.iterrows()):
                    col = tiles[i % len(tiles)]
                    with col:
                        col.metric(
                            f"{row['sla_name']} pct within",
                            f"{float(row['pct_within']):.1f}%",
                            help=f"Eligible: {int(row['n_eligible'])} · breached: {int(row['n_breached'])}",
                        )
                st.subheader("Current window summary")
                st.dataframe(sla, hide_index=True, width="stretch")

            if not trend.empty:
                st.subheader("Trend (weekly)")
                chart = (
                    alt.Chart(trend)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("week:O", title="Week"),
                        y=alt.Y("pct_within:Q", title="% within SLA"),
                        color=alt.Color("sla_name:N", title="SLA"),
                        tooltip=["week", "sla_name", alt.Tooltip("pct_within:Q", format=".1f")],
                    )
                    .properties(height=300)
                )
                st.altair_chart(chart, width="stretch")

    with tab_capacity:
        st.header("Capacity what-if")
        st.caption(
            "Simple capacity projection using Little's Law and a linear FTE scaling assumption."
        )
        if date_range is None:
            st.warning("Select a date range in the sidebar to anchor capacity inputs.")
        else:
            cap = qm.run(
                "capacity_inputs",
                product_type=product_filter,
                date_range=date_range,
            )
            if cap.empty:
                st.info("No capacity inputs for this filter.")
            else:
                inflow_per_day = float(cap.iloc[0]["inflow_per_day"] or 0.0)
                backlog_inflight = float(cap.iloc[0]["backlog_inflight"] or 0.0)
                ct_terminal = float(cap.iloc[0]["cycle_submit_to_terminal_p50"] or 0.0)
                ct_offer = float(cap.iloc[0]["cycle_submit_to_offer_p50"] or 0.0)
                ct_age = float(cap.iloc[0]["inflight_age_p50"] or 0.0)

                st.subheader("Inputs")
                c0, c1, c2 = st.columns(3)
                with c0:
                    inflow = st.number_input(
                        "Inflow per day (apps/day)",
                        min_value=0.0,
                        value=float(round(inflow_per_day, 3)),
                        step=0.1,
                    )
                with c1:
                    cr_fte = st.slider("CR FTE", min_value=0, max_value=20, value=8, step=1)
                with c2:
                    compliance_fte = st.slider(
                        "Compliance FTE", min_value=0, max_value=20, value=8, step=1
                    )

                st.subheader("Assumptions")
                a0, a1, a2 = st.columns([1, 1, 1])
                with a0:
                    base_fte = st.slider(
                        "Baseline FTE used for scaling",
                        min_value=1,
                        max_value=40,
                        value=16,
                        step=1,
                        help="We scale cycle time inversely with total (CR+Compliance) FTE vs this baseline.",
                    )
                with a1:
                    ct_kind = st.radio(
                        "Cycle time definition",
                        options=[
                            "Submit → terminal (completed only)",
                            "Submit → offer sent",
                            "In-flight age (since submit)",
                        ],
                        index=0,
                        horizontal=False,
                    )
                with a2:
                    override = st.checkbox("Override cycle time", value=False)

                if ct_kind == "Submit → offer sent":
                    suggested_ct = ct_offer
                elif ct_kind == "In-flight age (since submit)":
                    suggested_ct = ct_age
                else:
                    suggested_ct = ct_terminal

                if ct_kind == "Submit → offer sent":
                    st.info(
                        "Note: submit→offer can be much longer than ‘current backlog age’, so Little’s Law will "
                        "often predict a higher steady-state WIP than today’s in-flight backlog."
                    )

                current_cycle_time = (
                    st.number_input(
                        "Cycle time p50 (days) — override value",
                        min_value=0.0,
                        value=float(round(suggested_ct, 2)),
                        step=0.5,
                        disabled=not override,
                    )
                    if override
                    else float(suggested_ct)
                )

                from analytics.capacity import (
                    project_backlog_clear_days,
                    project_cycle_time_days,
                    project_wip,
                )

                total_fte = float(cr_fte + compliance_fte)
                projected_ct = project_cycle_time_days(
                    float(current_cycle_time),
                    base_fte=float(base_fte),
                    new_fte=total_fte,
                )
                projected_wip = project_wip(float(inflow), float(projected_ct))
                clear_days = project_backlog_clear_days(float(backlog_inflight), float(inflow))

                st.subheader("Outputs (steady-state, coarse)")
                o0, o1, o2 = st.columns(3)
                o0.metric("Current in-flight backlog", f"{int(backlog_inflight):,}")
                o1.metric("Projected cycle time p50 (days)", f"{projected_ct:.2f}")
                o2.metric("Projected WIP (apps)", f"{projected_wip:.1f}")

                delta = projected_wip - backlog_inflight
                st.caption(f"Consistency check: projected WIP − current WIP = **{delta:+.1f}** apps.")
                if abs(delta) > max(25.0, 0.5 * backlog_inflight):
                    st.warning(
                        "Projected WIP differs a lot from current WIP. "
                        "Try a different cycle time definition (or override) to match your planning goal."
                    )

                st.caption(
                    f"Backlog clear time at current inflow: **{clear_days:.1f} days** (naive: backlog/inflow)."
                )
                st.caption(
                    "Why this can look 'weird': Little’s Law uses **cycle time** (end-to-end time in the system) "
                    "and **throughput/inflow**. If your chosen cycle time definition (e.g. submit→offer) is much "
                    "larger than the current in-flight age/backlog would imply, the steady-state WIP estimate will "
                    "be much larger than today’s backlog."
                )


if __name__ == "__main__":
    main()

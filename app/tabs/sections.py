"""Per-tab bodies (moved from app.main)."""
from __future__ import annotations

import inspect

import streamlit as st
import streamlit.components.v1 as components
import altair as alt
import pandas as pd
from streamlit.column_config import DatetimeColumn, TextColumn

from analytics.legend import subtitle as legend_subtitle
from analytics.period_dashboard import load_period_dashboard
from analytics.query_manager import QueryManager
from analytics.team_productivity import (
    generate_staffing_calendar,
    generate_team_roster,
)
from app.tabs.constants import TERMINAL_STEP_ORDERS
from app.tabs.shared import (
    ClientFilters,
    filter_dataframe,
    investigation_launcher,
    investigation_scope_key,
    pct_delta,
    previous_date_range,
)
from app.tabs.viz_charts import *

# Period tab — full-screen Sankey (session state + st.dialog on_dismiss when Streamlit >= 1.48)
_PERIOD_SANKEY_FS_KEY = "period_transition_sankey_fs_open"
_PERIOD_SANKEY_PAYLOAD_KEY = "period_transition_sankey_fs_payload"


def _period_sankey_fs_dismiss() -> None:
    st.session_state[_PERIOD_SANKEY_FS_KEY] = False


def _period_sankey_modal_body() -> None:
    st.caption("Same edge filters as on the page. Close with ×, Esc, or the button below.")
    payload = st.session_state.get(_PERIOD_SANKEY_PAYLOAD_KEY)
    if not payload:
        st.warning("No Sankey payload — go back to Period and try again.")
        return
    edges = payload["edges"]
    if getattr(edges, "empty", False):
        st.info("No edges for this cohort.")
        return
    _transition_sankey_plotly_dialog(
        edges,
        stage_label=payload["stage_label"],
        top_k=int(payload["top_k"]),
        min_apps=int(payload["min_apps"]),
        include_self_loops=bool(payload["include_self_loops"]),
        prominent=True,
        chart_key="transition_sankey_plotly_fs",
    )
    if st.button("Close full-screen Sankey", key="period_sankey_modal_close_btn"):
        _period_sankey_fs_dismiss()
        st.rerun()


_dialog_kw: dict = {"width": "large"}
if "on_dismiss" in inspect.signature(st.dialog).parameters:
    _dialog_kw["on_dismiss"] = _period_sankey_fs_dismiss

period_transition_sankey_modal = st.dialog(
    "Stage-to-stage flow (full screen)",
    **_dialog_kw,
)(_period_sankey_modal_body)


def run_overview(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Overview")
    
    denom_df = qm.run("kpi_denom", product_type=product_filter, date_range=date_range)
    denom = int(denom_df.iloc[0]["n"]) if len(denom_df) else 0
    
    active_df = qm.run("kpi_active", product_type=product_filter, date_range=date_range)
    n_active = int(active_df.iloc[0]["n"]) if len(active_df) else 0
    
    avg_df = qm.run("kpi_avg_processing", product_type=product_filter, date_range=date_range)
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
    ball = qm.run(
        "who_has_the_ball",
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
    
    stale_df = (
        qm.run("kpi_inflight_stale_24h", product_type=product_filter, date_range=date_range)
        if date_range is not None
        else pd.DataFrame()
    )
    n_stale_24h = int(stale_df.iloc[0]["n_stale_24h"]) if len(stale_df) else 0
    st.caption("Stale 24h = in-flight apps whose last event is over 24h ago (excludes completed/cancelled).")
    st.metric("Stale in-flight (last event 24h+ ago)", f"{n_stale_24h:,}")
    
    # Full-width charts (stacked): half-width columns squeeze Altair and can force rotated SLA labels.
    st.markdown("**Throughput** (terminal/day + 7d MA dashed)")
    if thr.empty or date_range is None:
        st.caption("Select a date range to see the throughput series.")
    else:
        _throughput_daily_chart(thr)
    st.markdown("**SLA mix** (in-flight by area)")
    if sla.empty:
        st.caption("No in-flight rows for SLA breakdown.")
    else:
        _overview_sla_stacked_bars(sla)
    
    st.subheader("What needs attention")
    for insight in _executive_insights(
        n_active=n_active,
        n_stuck=n_stuck,
        pct_stuck=pct_stuck,
        thr_7d=thr_7d,
        thr_ma7=thr_ma7,
        sla=sla,
        ball=ball,
    ):
        st.markdown(f"- {insight}")
    
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
        if ball.empty:
            st.info("No in-flight applications in this filter.")
        else:
            _who_has_ball_chart(ball)
    with c_r:
        st.subheader("SLA status (in-flight) — table")
        st.caption(legend_subtitle("sla_breach_overview"))
        if sla.empty:
            st.info("No in-flight applications in this filter.")
        else:
            with st.expander("Raw counts by area and status", expanded=False):
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
        per_app = qm.run(
            "watchlist_enrichment",
            product_type=product_filter,
            date_range=None,
        )
        if not per_app.empty:
            watch = watch.merge(per_app, on="application_id", how="left")
        watch = filter_dataframe(
            watch,
            ui_filters,
            team_col="waiting_on",
            actor_col="latest_actor",
            stage_col=None,
        )
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
        investigation_launcher(
            watch,
            label="Send stuck case to App investigator",
            key="overview_watchlist_investigate",
            scope=investigation_scope_key(product_choice, date_range),
        )


def run_investigate(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Investigate")
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
    
            staged = qm.run(
                "application_staged_timeline",
                product_type=product_filter,
                date_range=None,
                application_id=inv_id,
            )
            if not staged.empty and len(staged) >= 2:
                st.subheader("In-stage residence (Gantt, segment between consecutive events)")
                st.caption("Each bar is the stage while the case stayed until the next audit row; not net dwell.")
                _investigator_staged_gantt(staged)
    
            dwell = qm.run(
                "application_dwell",
                product_type=product_filter,
                application_id=inv_id,
                date_range=None,
            )
            if not dwell.empty:
                st.subheader("Time in stage (hours)")
                med = qm.run(
                    "dwell_median_by_stage",
                    product_type=product_filter,
                    date_range=None,
                )
                _investigator_dwell_with_cohort_median(dwell, med)
    else:
        st.info("Enter an application UUID to load its audit trail.")


def run_cohort(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Cohort")
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
            st.markdown("**In-flight % (chart)**")
            _cohort_in_flight_line(kpi_df)
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
            st.markdown("**Survival curves (all horizons)**")
            _cohort_survival_lines(surv)
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
            st.markdown("**Time to first offer (p50 / p90)**")
            _cohort_time_to_offer_bars(tto)
    
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
        st.markdown("**Multi-KPI (charts)**")
        _cohort_multi_trajectory_charts(multi)
    
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
        st.markdown("**Cohort × stage (heatmap)**")
        _cohort_stage_heatmap(snap)
        pivot = snap.pivot_table(
            index="cohort_month",
            columns="step_order",
            values="n_applications",
            aggfunc="sum",
            fill_value=0,
        )
        st.dataframe(pivot, width="stretch")


def run_period(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
            st.header("Period")
            st.caption(
                f"Reporting window: **{date_range[0]}** → **{date_range[1]}** (inclusive, naive dates · PHASE_0 §2)."
                if date_range
                else "Select a date range in the sidebar to anchor period metrics."
            )
            if date_range is None:
                st.warning("Period SQL requires both start and end dates.")
            else:
                pd_board = load_period_dashboard(qm, product_type=product_filter, date_range=date_range)
                prev_range = previous_date_range(date_range)
                prev_board = load_period_dashboard(qm, product_type=product_filter, date_range=prev_range)
                cohort_n = int(pd_board.end_snapshot["active_applications"].sum())
                prev_cohort_n = int(prev_board.end_snapshot["active_applications"].sum())
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
                    delta=pct_delta(float(cohort_n), float(prev_cohort_n)),
                    help="Distinct applications with ≥1 audit row in the filter window + product (§5 In filter).",
                )
                r1c2.metric(
                    "Arrivals (first touch in window)",
                    f"{pd_board.n_arrivals:,}",
                    delta=pct_delta(float(pd_board.n_arrivals), float(prev_board.n_arrivals)),
                )
                r1c3.metric(
                    "Losses (terminal event in window)",
                    f"{pd_board.n_losses:,}",
                    delta=pct_delta(float(pd_board.n_losses), float(prev_board.n_losses)),
                )
                r1c4.metric(
                    "Movers (≥1 logical move)",
                    f"{pd_board.n_movers:,}",
                    delta=pct_delta(float(pd_board.n_movers), float(prev_board.n_movers)),
                )
    
                r2c1, r2c2, r2c3 = st.columns(3)
                r2c1.metric(
                    "Apps in terminal stage (start snapshot)",
                    f"{start_term:,}",
                    help="Count in funnel buckets 17/18/22/26 at start-of-period snapshot.",
                )
                r2c2.metric("Apps in terminal stage (end snapshot)", f"{end_term:,}")
                r2c3.metric("Δ terminal bucket (end − start)", f"{end_term - start_term:,}")
    
                with st.expander("Prior-period details", expanded=False):
                    st.caption(f"Previous comparison window: **{prev_range[0]}** → **{prev_range[1]}**.")
                    st.dataframe(
                        pd.DataFrame(
                            [
                                ["Cohort", cohort_n, prev_cohort_n, cohort_n - prev_cohort_n],
                                ["Arrivals", pd_board.n_arrivals, prev_board.n_arrivals, pd_board.n_arrivals - prev_board.n_arrivals],
                                ["Losses", pd_board.n_losses, prev_board.n_losses, pd_board.n_losses - prev_board.n_losses],
                                ["Movers", pd_board.n_movers, prev_board.n_movers, pd_board.n_movers - prev_board.n_movers],
                            ],
                            columns=["metric", "current", "previous", "delta"],
                        ),
                        hide_index=True,
                        width="stretch",
                    )
    
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
    
                st.subheader("Start vs end — same cohort (largest stages by volume)")
                st.caption(
                    "Stacked by snapshot side: for each process stage, how many applications were in that bucket at "
                    "start-of-period vs end-of-period (latest pre-window stage vs end-of-window stage)."
                )
                start_plot2 = pd_board.start_snapshot.query("active_applications > 0").copy()
                if not start_plot2.empty or not end_plot.empty:
                    _period_start_end_grouped_bars(start_plot2, end_plot)
                else:
                    st.caption("No data for start vs end stage comparison in this window.")
    
                if not start_plot2.empty or not end_plot.empty:
                    st.subheader("Net change in stage mix (end − start)")
                    _period_net_stage_delta_chart(start_plot2, end_plot)
    
                movers_prod = qm.run(
                    "period_movers_by_product",
                    product_type=product_filter,
                    date_range=date_range,
                )
                if not movers_prod.empty:
                    st.subheader("Movers in period, by product type")
                    st.caption("Applications with ≥1 in-window transition, attributed to the app’s first product row.")
                    c_mp = (
                        alt.Chart(movers_prod)
                        .mark_bar()
                        .encode(
                            x=alt.X("n_movers:Q", title="Movers (apps)"),
                            y=alt.Y("product_type:N", sort="-x", title="Product type"),
                            tooltip=["product_type", "n_movers"],
                        )
                        .properties(height=max(120, 28 * len(movers_prod)))
                    )
                    st.altair_chart(c_mp, width="stretch")
    
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
                                "Top edges to display (heatmap, bars, Sankey)",
                                min_value=15,
                                max_value=100,
                                value=50,
                                step=5,
                                key="period_flow_top_k",
                            )
                        )
                        min_apps = int(
                            st.slider(
                                "Min apps per edge",
                                min_value=1,
                                max_value=250,
                                value=5,
                                step=1,
                                key="period_flow_min_apps",
                            )
                        )
                    with right:
                        include_self = bool(
                            st.checkbox("Include self-loops", value=False, key="period_flow_self_loops")
                        )
                        hide_routine = bool(
                            st.checkbox(
                                "Hide routine full-cohort edges",
                                value=True,
                                help="Removes edges that carry almost the whole cohort, such as the standard intake steps.",
                                key="period_flow_hide_routine",
                            )
                        )
                        st.caption(
                            "Sankey uses Apache ECharts (not Plotly). If it looks like a tangled mess, lower “Top edges” "
                            "or raise “Min apps”."
                        )
    
                    flow_edges = edges.copy()
                    if hide_routine:
                        routine_cutoff = max(1, int(0.90 * cohort_n))
                        flow_edges = flow_edges.loc[flow_edges["n_apps"] < routine_cutoff].copy()
                        if flow_edges.empty:
                            st.info("All visible transitions are routine full-cohort moves; showing the unfiltered flow.")
                            flow_edges = edges.copy()
    
                    st.divider()
                    st.subheader("Stage-to-stage Sankey")
                    st.caption(
                        "Always visible by default. Full stage names appear in the mapping table under the chart."
                    )
                    if _PERIOD_SANKEY_FS_KEY not in st.session_state:
                        st.session_state[_PERIOD_SANKEY_FS_KEY] = False
                    st.session_state[_PERIOD_SANKEY_PAYLOAD_KEY] = {
                        "edges": flow_edges,
                        "stage_label": mlab,
                        "top_k": top_k,
                        "min_apps": min_apps,
                        "include_self_loops": include_self,
                        "chart_height_px": 980,
                    }
                    if st.button("Open Sankey full screen", key="period_sankey_open_dialog"):
                        st.session_state[_PERIOD_SANKEY_FS_KEY] = True
                    if st.session_state[_PERIOD_SANKEY_FS_KEY]:
                        period_transition_sankey_modal()

                    _transition_sankey(
                        flow_edges,
                        stage_label=mlab,
                        top_k=top_k,
                        min_apps=min_apps,
                        include_self_loops=include_self,
                        compact_node_labels=False,
                        prominent=True,
                        chart_key="transition_sankey_echarts_embed",
                    )
    
                    bars_col, heat_col = st.columns([1, 1])
                    with bars_col:
                        st.markdown("**Largest transitions**")
                        _transition_edge_bars(
                            flow_edges,
                            top_k=top_k,
                            min_apps=min_apps,
                            include_self_loops=include_self,
                        )
                    with heat_col:
                        st.markdown("**Transition concentration**")
                        _transition_heatmap(
                            flow_edges,
                            top_k=top_k,
                            min_apps=min_apps,
                            include_self_loops=include_self,
                        )
    
                    with st.expander("Show transition edges as a table", expanded=False):
                        show = edges[
                            ["from_label", "from_stage", "to_label", "to_stage", "n_apps"]
                        ].sort_values("n_apps", ascending=False)
                        st.dataframe(show, hide_index=True, width="stretch")

                daily_al = qm.run(
                    "period_arrivals_losses_by_day",
                    product_type=product_filter,
                    date_range=date_range,
                )
                st.subheader("Arrivals and terminal events by day (in period)")
                st.caption(
                    "Blue: first product-filtered audit day per cohort app. Red: distinct apps with any terminal "
                    "action that day (includes successful master-data submission, not only reject/cancel). "
                    "Terminal can be higher than arrivals: many cohort apps may finish on the same day; "
                    "arrivals only count apps whose first audit day is that calendar day."
                )
                if not daily_al.empty:
                    _period_arrivals_losses_by_day(daily_al)
                else:
                    st.caption("No per-day series for this window.")


def run_bottleneck(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Bottleneck")
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
            top = radar.iloc[0]
            total_wip = int(radar["wip_now"].sum())
            aging_7d = int(radar["aging_7d_plus"].sum())
            b0, b1, b2 = st.columns(3)
            b0.metric("Total WIP in bottleneck view", f"{total_wip:,}")
            b1.metric("WIP aged 7d+", f"{aging_7d:,}")
            b2.metric("Top bottleneck", str(top["step_label"]).split("·", 1)[0].strip())
    
            left, right = st.columns([1, 1])
            with left:
                st.subheader("Ranked bottlenecks")
                _bottleneck_score_chart(radar)
            with right:
                st.subheader("Open WIP aging (stacked buckets)")
                _bottleneck_aging_chart(radar)
    
            st.subheader("Inflow vs outflow (7d, end of window)")
            _bottleneck_inflow_outflow_chart(radar)
    
            cases = qm.run(
                "bottleneck_cases",
                product_type=product_filter,
                date_range=date_range,
            )
            top_stages = radar.head(3)["stage_order"].tolist()
            focus_cases = cases.loc[cases["stage_order"].isin(top_stages)].head(10) if not cases.empty else pd.DataFrame()
            focus_cases = filter_dataframe(
                focus_cases,
                ui_filters,
                team_col=None,
                actor_col="latest_actor",
                stage_col="stage_order",
            )
            st.subheader("Cases to inspect")
            if focus_cases.empty:
                st.info("No open cases in the top bottleneck stages.")
            else:
                st.dataframe(focus_cases, hide_index=True, width="stretch")
                investigation_launcher(
                    focus_cases,
                    label="Send bottleneck case to App investigator",
                    key="bottleneck_case_investigate",
                    scope=investigation_scope_key(product_choice, date_range),
                )
    
            with st.expander("Show full bottleneck table", expanded=False):
                st.dataframe(radar, hide_index=True, width="stretch")


def run_rework(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Rework")
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
        cases = qm.run(
            "rework_cases",
            product_type=product_filter,
            date_range=date_range,
        )
        if overall.empty:
            st.info("No rows for this filter.")
        else:
            row = overall.iloc[0]
            total = int(row["n_apps_total"])
            loop2 = int(row["n_apps_2plus_interactions"])
            reopened = int(row["n_apps_with_compliance_reopened"])
            answers_edit = int(row["n_apps_with_answers_edit"])
            r0, r1, r2, r3 = st.columns(4)
            r0.metric("Applications", f"{total:,}")
            r1.metric("2+ interaction loops", f"{loop2:,}")
            r2.metric("Compliance reopened", f"{reopened:,}")
            r3.metric("Answers edited", f"{answers_edit:,}")
        if not by_prod.empty:
            st.subheader("Loop rate by product")
            _rework_product_chart(by_prod)
    
        dist = qm.run(
            "rework_interaction_dist",
            product_type=product_filter,
            date_range=date_range,
        )
        st.subheader("Interaction loops in cohort (distribution)")
        st.caption("How many times INTERACTION_STARTED fired per app in the selected window and product.")
        if dist.empty:
            st.caption("No distribution data for this filter.")
        else:
            _rework_interaction_dist_chart(dist)
    
        out_loops = qm.run(
            "rework_outcome_by_loops",
            product_type=product_filter,
            date_range=date_range,
        )
        if not out_loops.empty:
            st.subheader("Offer reach by interaction intensity")
            _rework_outcome_offer_rate_chart(out_loops)
    
        cases_view = filter_dataframe(
            cases.copy(),
            ui_filters,
            team_col="primary_team",
            actor_col="latest_actor",
            stage_col=None,
        )

        st.subheader("Cases to inspect")
        if cases.empty:
            st.info("No high-rework cases for this filter.")
        elif cases_view.empty:
            st.info(
                "No cases match **View filters** (team / actor). "
                "Set Team to **(All)** or clear actor text."
            )
        else:
            st.dataframe(cases_view.head(10), hide_index=True, width="stretch")
            investigation_launcher(
                cases_view,
                label="Send rework case to App investigator",
                key="rework_case_investigate",
                scope=investigation_scope_key(product_choice, date_range),
            )
    
        with st.expander("Show raw rework tables", expanded=False):
            if not overall.empty:
                st.dataframe(overall, hide_index=True, width="stretch")
            if not by_prod.empty:
                st.dataframe(by_prod, hide_index=True, width="stretch")


def run_team(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Team")
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
            wl = filter_dataframe(wl, ui_filters, team_col="team", actor_col="actor", stage_col=None)
    
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
    
            team_day = qm.run(
                "team_completions_by_day",
                product_type=product_filter,
                date_range=date_range,
            )
            st.subheader("Completions by actor and day (heatmap)")
            st.caption("Terminal outcomes per day; top actors by total completions in the period.")
            if team_day.empty:
                st.caption("No per-day completion rows for this window.")
            else:
                _team_closures_heatmap(team_day)
    
            tact = qm.run(
                "team_actor_outcomes",
                product_type=product_filter,
                date_range=date_range,
            )
            if not tact.empty:
                st.subheader("Terminal outcome mix (last 30d, by actor)")
                _team_actor_outcome_chart(tact)
    
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
                team_cases = qm.run(
                    "team_attention_cases",
                    product_type=product_filter,
                    date_range=date_range,
                )
                attention_actors = set(attention["actor"].astype(str).tolist())
                team_cases = team_cases.loc[team_cases["actor"].astype(str).isin(attention_actors)].head(10)
                if not team_cases.empty:
                    st.markdown("**Attention cases**")
                    st.dataframe(team_cases, hide_index=True, width="stretch")
                    investigation_launcher(
                        team_cases,
                        label="Send team workload case to App investigator",
                        key="team_case_investigate",
                        scope=investigation_scope_key(product_choice, date_range),
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


def run_sla(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("SLA")
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
            line = alt.Chart(trend).mark_line(point=True, strokeWidth=1.1).encode(
                x=alt.X("week:O", title="Week"),
                y=alt.Y("pct_within:Q", title="% within SLA", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color("sla_name:N", title="SLA"),
                tooltip=["week", "sla_name", alt.Tooltip("pct_within:Q", format=".1f")],
            )
            target = (
                alt.Chart(pd.DataFrame({"y": [90.0]}))
                .mark_rule(strokeDash=[4, 3], color="#94a3b8")
                .encode(y="y:Q")
            )
            c = (line + target).properties(height=300)
            st.caption("Grey dashed line: 90% within-SLA target (illustrative).")
            st.altair_chart(c, width="stretch")
            st.subheader("Weekly % within (heatmap)")
            _sla_weekly_heatmap(trend)
    
        breach_rows = qm.run(
            "sla_breached_applications",
            product_type=product_filter,
            date_range=date_range,
        )
        st.subheader("Currently breached in-flight (cohort, top 25)")
        st.caption("Same SLA clock rules as the overview; limited to 200 rows in SQL, shows top 25 here.")
        if breach_rows.empty:
            st.caption("No breaches for this product/date filter.")
        else:
            st.dataframe(breach_rows.head(25), hide_index=True, width="stretch")
            investigation_launcher(
                breach_rows.head(25),
                label="Load breached case in App investigator",
                key="sla_breach_investigate",
                scope=investigation_scope_key(product_choice, date_range),
            )


def run_capacity(*, qm: QueryManager, product_filter, date_range, min_d, max_d, product_choice: str, ui_filters: ClientFilters) -> None:
    st.header("Capacity")
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
    
            st.subheader("Scenario vs today (WIP, cycle time, FTE mix)")
            _capacity_scenario_bars(
                backlog=float(backlog_inflight),
                projected_wip=float(projected_wip),
                current_ct=float(current_cycle_time),
                projected_ct=float(projected_ct),
                cr_fte=int(cr_fte),
                compliance_fte=int(compliance_fte),
            )

            st.subheader("Employees working on Wednesdays")
            st.caption(
                "Mock staffing calendar (same generator as **Team → Capacity calendars**): "
                "CR + Compliance rosters (8 each). "
                "**Working** = availability > 0% that Wednesday."
            )
            _ws, _we = _date_range_days(date_range)
            _ro_cr = generate_team_roster("CR", n_people=8)
            _ro_co = generate_team_roster("Compliance", n_people=8)
            _sched_wed = pd.concat(
                [
                    generate_staffing_calendar(
                        actors=_ro_cr,
                        team="CR",
                        start_day=_ws,
                        end_day=_we,
                        seed=42,
                    ),
                    generate_staffing_calendar(
                        actors=_ro_co,
                        team="Compliance",
                        start_day=_ws,
                        end_day=_we,
                        seed=42,
                    ),
                ],
                ignore_index=True,
            )
            _capacity_wednesday_employee_bars(_sched_wed)
    
            delta = projected_wip - backlog_inflight
            st.caption(f"Consistency check: projected WIP − current WIP = **{delta:+.1f}** apps.")
            if abs(delta) > max(25.0, 0.5 * backlog_inflight):
                st.warning(
                    "Projected WIP differs a lot from current WIP. "
                    "Try a different cycle time definition (or override) to match your planning goal."
                )
    
            st.subheader("FTE sweep (1–40 total) at current inflow and cycle time")
            _capacity_fte_sweep_chart(
                inflow=float(inflow),
                current_cycle_time=float(current_cycle_time),
                base_fte=int(base_fte),
                backlog=float(backlog_inflight),
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
    

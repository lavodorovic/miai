"""
Centralized chart/table subtitles (PHASE_0 §5 + Phase 1b).

Pattern: unit (per application vs per transition), during vs as-of, cohort anchor.
"""

from __future__ import annotations

# Keys are stable ids for Streamlit / SQL footers; values are user-facing strings.

LEGENDS: dict[str, dict[str, str]] = {
    "kpi_in_filter": {
        "subtitle": (
            "Per application · During selected date range (inclusive dates, naive timestamps per §2) · "
            "Cohort anchor: any activity in filter (PHASE_0 §5 ‘In filter’; strict ‘submitted’ anchor is §4 PM option)."
        ),
    },
    "kpi_in_flight": {
        "subtitle": (
            "Per application · As of now (latest audit row) among cohort members · "
            "Excludes terminal actions listed in SQL (PHASE_0 §5 ‘In-flight’)."
        ),
    },
    "kpi_avg_processing": {
        "subtitle": (
            "Per application (then averaged) · Mixed: cohort during window; span uses full history after submit · "
            "PHASE_0 §5."
        ),
    },
    "kpi_pct_stuck": {
        "subtitle": (
            "Per application · Dataset as-of (max audit timestamp) vs last event (>48h) · "
            "Denominator = in-flight cohort · PHASE_0 §5."
        ),
    },
    "overview_completions_metrics": {
        "subtitle": (
            "Terminal outcomes (distinct applications) · Last 30 days ending at max(timestamp); "
            "‘Change vs 90d trend’ compares that count to the pace implied by completions in the prior 90 days "
            "(expected 30d ≈ prior-90d total ÷ 3) · Product/date filters apply."
        ),
    },
    "overview_performance_weekly": {
        "subtitle": (
            "Business Account only · Distinct applications per ISO week · New applications = APPLICATION_STARTED; "
            "terminal stage = any terminal action; new customers = MASTER_DATA_SUBMITTED · Weekly buckets from audit timestamps."
        ),
    },
    "funnel_latest_stage": {
        "subtitle": (
            "Per application (each counted once in exactly one bar) · As of now (latest mapped stage) · "
            "Cohort: ≥1 audit row during selected date range + product; latest uses full history for those IDs · "
            "PHASE_0 §1–§2, §5. Not a flow diagram (no inter-stage connectors)."
        ),
    },
    "funnel_swimlanes": {
        "subtitle": (
            "Per application (each counted once in exactly one swimlane) · As of now (latest mapped stage) · "
            "Cohort: ≥1 audit row during selected date range + product; latest uses full history for those IDs · "
            "Collapsed view of the 34-step funnel."
        ),
    },
    "who_has_the_ball": {
        "subtitle": (
            "Per application · As of now (latest audit row) among in-flight apps · "
            "Team is derived from action/actor via v_team."
        ),
    },
    "throughput_daily": {
        "subtitle": (
            "Per terminal event (distinct application_id) · During selected date range · "
            "Shows daily terminal outcomes and 7-day moving average."
        ),
    },
    "sla_breach_overview": {
        "subtitle": (
            "Per application · As of now among in-flight apps · "
            "Buckets by SLA area with ok/at-risk/breached based on hours since last event (v0 thresholds in SQL)."
        ),
    },
    "funnel_bar_sum": {
        "subtitle": (
            "Sanity: sum of bar heights = in-filter cohort (each app’s latest stage is one bucket)."
        ),
    },
    "watchlist_stuck": {
        "subtitle": (
            "Per application · As of now · In-flight only; latest event >48h old · "
            "Case owner from assignment events; latest actor = last audit actor · PHASE_0 §5."
        ),
    },
    "period_start_snapshot": {
        "subtitle": (
            "Per application (one bucket each) · As of calendar day before period start "
            "(latest stage from rows with timestamp::DATE < start; naive §2) · "
            "Cohort: same ‘in filter’ window + product as other period blocks."
        ),
    },
    "period_end_snapshot": {
        "subtitle": (
            "Per application · As of period end (timestamp::DATE ≤ end inclusive) · "
            "Same cohort as start snapshot; sum of bars = cohort size."
        ),
    },
    "period_arrivals_losses": {
        "subtitle": (
            "Arrivals: per application · During window — first product-filtered audit day in [start,end]. "
            "Red series is “terminal events” per day (distinct apps with any terminal action that day), "
            "including successful MASTER_DATA_SUBMITTED as well as reject / cancel / offer refused — "
            "same terminal set as §5 in-flight exclusion, not “churn only”."
        ),
    },
    "period_transition_matrix": {
        "subtitle": (
            "Per application-edge (distinct apps per from→to at least once) · During window — "
            "transition_at::DATE inclusive BETWEEN start/end · Cohort membership unchanged (§2/§3)."
        ),
    },
    "cohort_single_kpi": {
        "subtitle": (
            "Per application (one row per app in each cohort month) · As of selected calendar day (naive) · "
            "Cohort by anchor month (§4); apps with missing anchor excluded · KPI = % in-flight vs terminals (§5)."
        ),
    },
    "cohort_status_snapshot": {
        "subtitle": (
            "Per application (summed into counts) · As of same date · "
            "Distribution of latest stage_order by cohort month (long format for pivot)."
        ),
    },
    "cohort_anchor_excluded": {
        "subtitle": (
            "Per application · No as-of window — counts product-filtered apps with NULL anchor for the selected anchor definition (§4 exclude path)."
        ),
    },
}


def subtitle(metric_id: str) -> str:
    if metric_id not in LEGENDS:
        raise KeyError(f"Unknown legend id: {metric_id}")
    return LEGENDS[metric_id]["subtitle"]

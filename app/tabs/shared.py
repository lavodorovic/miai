from __future__ import annotations

import hashlib
from dataclasses import dataclass

import altair as alt
import pandas as pd
import streamlit as st


def previous_date_range(date_range: tuple[str, str]) -> tuple[str, str]:
    start_s, end_s = (str(date_range[0])[:10], str(date_range[1])[:10])
    start = pd.to_datetime(start_s)
    end = pd.to_datetime(end_s)
    days = (end - start).days + 1
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days - 1)
    return prev_start.date().isoformat(), prev_end.date().isoformat()


def pct_delta(current: float, previous: float) -> str:
    if previous == 0:
        return "n/a" if current == 0 else "+new"
    return f"{((current - previous) / previous) * 100.0:+.1f}%"


def set_investigation_target(application_id: object) -> None:
    app_id = str(application_id or "").strip()
    if app_id:
        st.session_state["investigate_app_id"] = app_id


@dataclass
class ClientFilters:
    """
    Post-query filters in the UI (no SQL changes). team=None = all; stage_order None = all.
    """

    team: str | None = None
    actor_substr: str = ""
    stage_order: int | None = None


def filter_dataframe(
    df: pd.DataFrame,
    filters: ClientFilters,
    *,
    team_col: str | None = "team",
    actor_col: str | None = "actor",
    stage_col: str | None = "stage_order",
) -> pd.DataFrame:
    """Return a copy of ``df`` restricted by the optional column filters (best-effort)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    if filters.team and team_col is not None and team_col in out.columns:
        out = out.loc[out[team_col].astype(str) == str(filters.team)]
    if filters.actor_substr and actor_col and actor_col in out.columns:
        pat = str(filters.actor_substr).lower()
        out = out.loc[out[actor_col].astype(str).str.lower().str.contains(pat, na=False)]
    if filters.stage_order is not None and stage_col and stage_col in out.columns:
        out = out.loc[out[stage_col].astype(int) == int(filters.stage_order)]
    return out


def render_sidebar_client_filters(*, enabled: bool = True) -> ClientFilters:
    """Add controls under the main sidebar; return a ClientFilters to apply in tabs."""
    if not enabled:
        return ClientFilters()
    st.sidebar.subheader("View filters (subset of loaded rows)")
    t = st.sidebar.selectbox("Team (optional)", ["(All)", "CR", "Compliance"], key="ui_filter_team")
    a = st.sidebar.text_input("Actor text contains (optional)", value="", key="ui_filter_actor", max_chars=64)
    s = st.sidebar.number_input("Stage order (0 = any)", 0, 40, 0, key="ui_filter_stage")
    return ClientFilters(
        team=None if t == "(All)" else str(t),
        actor_substr=(a or "").strip().lower(),
        stage_order=None if int(s) == 0 else int(s),
    )


def stage_category_color() -> list[str]:
    """Consistent 8-color palette for categorical process layers (funnel, swimlane)."""
    return ["#4C78A8", "#59A14F", "#F28E2B", "#B07AA1", "#76B7B2", "#EDC948", "#E15759", "#9C755F"]


def swimlane_color_scale() -> alt.Scale:
    """Altair color scale re-used for swimlane / team charts."""
    c = stage_category_color()
    d = [f"Lane {i + 1}" for i in range(len(c))]
    return alt.Scale(domain=d, range=c)


def _widget_scope_suffix(scope: str) -> str:
    """Short stable suffix so Streamlit widget keys reset when upstream filters (e.g. product) change."""
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:12]


def investigation_scope_key(product_choice: str, date_range: tuple[str, str] | None) -> str:
    """Stable scope string for widgets whose options depend on sidebar product + date window."""
    if date_range is None:
        return f"{product_choice}|nodr"
    a, b = date_range
    return f"{product_choice}|{a}|{b}"


def investigation_launcher(
    df: pd.DataFrame,
    *,
    label: str,
    key: str,
    app_col: str = "application_id",
    scope: str,
) -> None:
    """scope should reflect filters that change the option list (e.g. sidebar product choice)."""
    if df.empty or app_col not in df.columns:
        return
    options = [str(x) for x in df[app_col].dropna().astype(str).unique().tolist()]
    if not options:
        return
    suf = _widget_scope_suffix(scope)
    selected = st.selectbox(label, options=options, key=f"{key}::{suf}::select")
    if st.button("Load in App investigator", key=f"{key}::{suf}::button"):
        set_investigation_target(selected)
        st.success("Loaded. Open the App investigator tab to view the audit trail.")

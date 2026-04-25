from __future__ import annotations

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


def investigation_launcher(
    df: pd.DataFrame,
    *,
    label: str,
    key: str,
    app_col: str = "application_id",
) -> None:
    if df.empty or app_col not in df.columns:
        return
    options = [str(x) for x in df[app_col].dropna().astype(str).unique().tolist()]
    if not options:
        return
    selected = st.selectbox(label, options=options, key=f"{key}::select")
    if st.button("Load in App investigator", key=f"{key}::button"):
        set_investigation_target(selected)
        st.success("Loaded. Open the App investigator tab to view the audit trail.")

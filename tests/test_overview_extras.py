from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


TERMINAL_ACTIONS = (
    "MASTER_DATA_SUBMITTED",
    "APPLICATION_REJECTED",
    "APPLICATION_CANCELLED",
    "OFFER_REFUSED",
)


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)


def test_funnel_swimlanes_has_expected_rows() -> None:
    con = _connect()
    qm = QueryManager(con)
    df = qm.run("funnel_swimlanes", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert len(df) == 8
    assert set(df["swimlane_order"]) == set(range(1, 9))


def test_who_has_the_ball_sums_to_inflight() -> None:
    con = _connect()
    qm = QueryManager(con)
    ball = qm.run("who_has_the_ball", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    n_ball = int(ball["n_applications"].sum()) if len(ball) else 0

    inflight = int(
        con.sql(
            """
            WITH latest AS (
                SELECT
                    application_id,
                    arg_max(action, timestamp) AS last_action
                FROM audit_logs
                GROUP BY application_id
            )
            SELECT COUNT(*) FROM latest
            WHERE last_action NOT IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
            """
        ).fetchone()[0]
    )
    assert n_ball == inflight


def test_throughput_daily_matches_period_losses_terminal_events() -> None:
    con = _connect()
    qm = QueryManager(con)
    dr = ("2026-04-04", "2026-04-24")
    thr = qm.run("throughput_daily", product_type=None, date_range=dr)
    n_thr = int(thr["n_terminated"].sum()) if len(thr) else 0

    losses = int(
        con.sql(
            """
            SELECT COUNT(DISTINCT application_id) AS n
            FROM audit_logs
            WHERE timestamp::DATE BETWEEN DATE '2026-04-04' AND DATE '2026-04-24'
              AND action IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
            """
        ).fetchone()[0]
    )
    assert n_thr == losses


def test_kpi_inflight_stale_24h_runs() -> None:
    con = _connect()
    qm = QueryManager(con)
    df = qm.run("kpi_inflight_stale_24h", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert "n_stale_24h" in df.columns
    assert int(df.iloc[0]["n_stale_24h"]) >= 0


def test_sla_breach_overview_has_only_expected_statuses() -> None:
    con = _connect()
    qm = QueryManager(con)
    df = qm.run("sla_breach_overview", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert set(df["status"].unique()) <= {"ok", "at_risk", "breached"}
    assert set(df["sla_area"].unique()) <= {
        "CR review",
        "Compliance",
        "Interaction / RFI",
        "Offer & onboarding",
        "Other",
    }


def test_named_overview_kpi_queries_return_single_row() -> None:
    con = _connect()
    qm = QueryManager(con)
    dr = ("2026-04-04", "2026-04-24")
    for name in ["kpi_denom", "kpi_active", "kpi_avg_processing"]:
        df = qm.run(name, product_type=None, date_range=dr)
        assert len(df) == 1


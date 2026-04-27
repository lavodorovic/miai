from __future__ import annotations

from pathlib import Path

import duckdb

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


def test_team_workload_has_expected_teams_and_flags() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("team_workload", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert set(df["team"].unique()) <= {"CR", "Compliance"}
    assert df["open_cases_now"].min() >= 0


def test_team_workload_open_cases_is_not_more_than_inflight() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("team_workload", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    open_sum = int(df["open_cases_now"].sum()) if len(df) else 0
    inflight = int(
        con.sql(
            """
            WITH latest AS (
                SELECT application_id, arg_max(action, timestamp) AS last_action
                FROM audit_logs
                GROUP BY application_id
            )
            SELECT COUNT(*) FROM latest
            WHERE last_action NOT IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
            """
        ).fetchone()[0]
    )
    assert open_sum <= inflight


def test_team_attention_cases_are_investigable() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("team_attention_cases", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert {"application_id", "actor", "team", "days_in_stage"}.issubset(df.columns)


def test_team_actor_outcomes_shape() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("team_actor_outcomes", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert {"actor", "team", "n_approved", "n_rejected", "n_other_terminal"}.issubset(df.columns)
    con.close()


def test_team_completions_by_day_shape() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("team_completions_by_day", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert {"day", "actor", "team", "n_completions"}.issubset(df.columns)
    assert (df["n_completions"] >= 0).all()


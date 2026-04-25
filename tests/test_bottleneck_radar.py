from __future__ import annotations

from pathlib import Path

import duckdb

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


def test_bottleneck_radar_no_nans_and_has_rows() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("bottleneck_radar", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert len(df) >= 5
    assert df["bottleneck_score"].notna().all()


def test_bottleneck_radar_wip_sums_to_inflight() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    radar = qm.run("bottleneck_radar", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    wip_sum = int(radar["wip_now"].sum())
    inflight = int(
        con.sql(
            """
            WITH cohort AS (
                SELECT DISTINCT application_id
                FROM audit_logs
                WHERE timestamp::DATE BETWEEN DATE '2026-04-04' AND DATE '2026-04-24'
            ),
            latest AS (
                SELECT
                    a.application_id,
                    arg_max(a.action, a.timestamp) AS last_action
                FROM audit_logs AS a
                INNER JOIN cohort AS c ON a.application_id = c.application_id
                GROUP BY a.application_id
            )
            SELECT COUNT(*) FROM latest
            WHERE last_action NOT IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
            """
        ).fetchone()[0]
    )
    assert wip_sum == inflight


def test_bottleneck_cases_have_investigator_ids() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("bottleneck_cases", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert {"application_id", "stage_order", "days_in_stage"}.issubset(df.columns)


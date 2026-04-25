from __future__ import annotations

from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent.parent


def test_v_team_rowcount_matches_audit_logs() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    n_audit = int(con.sql("SELECT COUNT(*) FROM audit_logs").fetchone()[0])
    n_team = int(con.sql("SELECT COUNT(*) FROM v_team").fetchone()[0])
    assert n_team == n_audit


def test_v_stage_dwell_has_one_open_entry_per_app() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    rows = con.sql(
        """
        SELECT
            application_id,
            SUM(CASE WHEN is_open THEN 1 ELSE 0 END) AS n_open
        FROM v_stage_dwell
        GROUP BY application_id
        """
    ).fetchall()
    assert rows, "expected at least one application in DB"
    assert all(int(n_open) == 1 for _, n_open in rows)


def test_v_stage_dwell_entries_match_contiguous_stage_runs() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    # Count of stage-entries derived directly from v_audit_staged by contiguous-stage rule.
    n_expected = int(
        con.sql(
            """
            WITH ordered AS (
                SELECT
                    application_id,
                    stage_order,
                    LAG(stage_order) OVER (
                        PARTITION BY application_id
                        ORDER BY timestamp, action
                    ) AS prev_stage
                FROM v_audit_staged
            )
            SELECT COUNT(*) FROM ordered
            WHERE prev_stage IS NULL OR stage_order IS DISTINCT FROM prev_stage
            """
        ).fetchone()[0]
    )
    n_actual = int(con.sql("SELECT COUNT(*) FROM v_stage_dwell").fetchone()[0])
    assert n_actual == n_expected


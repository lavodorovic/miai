"""Phase 5 — CI-safe checks: transition drift + period end vs cohort (when DB + range available)."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from analytics.ddl_loader import apply_ddl  # noqa: E402
from analytics.period_dashboard import load_period_dashboard  # noqa: E402
from analytics.query_manager import QueryManager  # noqa: E402
from synthetic_generator import (  # noqa: E402
    anchor_application_timelines,
    generate_synthetic_audit_log,
    write_audit_outputs,
)


def test_transition_drift_sql_is_zero_on_synthetic_db() -> None:
    db = ROOT / "data" / "relio_analytics.db"
    if not db.is_file():
        pytest.skip("relio_analytics.db missing")
    con = duckdb.connect(str(db), read_only=True)
    try:
        drift = con.execute(
            (ROOT / "analytics/queries/transition_latest_drift_check.sql").read_text(encoding="utf-8")
        ).fetchone()[0]
        assert drift == 0
    finally:
        con.close()


@pytest.fixture
def gate_db(tmp_path: Path):
    import pandas as pd

    df = generate_synthetic_audit_log(4, seed=3, anchor_timelines=False)
    end = pd.Timestamp("2026-05-10T12:00:00")
    df = anchor_application_timelines(df, timeline_end=end, seed=3)
    csv_path = tmp_path / "g.csv"
    write_audit_outputs(df, parquet_path=str(tmp_path / "g.parquet"), duckdb_csv_path=str(csv_path))
    con = duckdb.connect(str(tmp_path / "g.db"))
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)", [str(csv_path)])
    apply_ddl(con, ROOT)
    try:
        yield con
    finally:
        con.close()


def test_period_end_matches_cohort_gate(gate_db: duckdb.DuckDBPyConnection) -> None:
    bounds = gate_db.execute(
        "SELECT CAST(MIN(timestamp) AS DATE), CAST(MAX(timestamp) AS DATE) FROM audit_logs"
    ).fetchone()
    dr = (str(bounds[0]), str(bounds[1]))
    qm = QueryManager(gate_db)
    drift_sql = (ROOT / "analytics/queries/transition_latest_drift_check.sql").read_text(encoding="utf-8")
    drift = int(gate_db.execute(drift_sql).fetchdf().iloc[0]["drift_rows"])
    assert drift == 0
    pd_data = load_period_dashboard(qm, product_type=None, date_range=dr)
    cohort_n = int(
        qm.run_sql(
            """
            SELECT COUNT(DISTINCT application_id)::BIGINT AS n
            FROM audit_logs
            WHERE {{PRODUCT_TYPE_FILTER}} AND {{DATE_RANGE_FILTER}}
            """,
            product_type=None,
            date_range=dr,
        ).iloc[0]["n"]
    )
    assert int(pd_data.end_snapshot["active_applications"].sum()) == cohort_n

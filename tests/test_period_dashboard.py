"""Phase 2: period snapshots, arrivals/losses, transition matrix (PHASE_0 §2–§3)."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
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


@pytest.fixture
def period_db(tmp_path: Path):
    df = generate_synthetic_audit_log(5, seed=42, anchor_timelines=False)
    end = pd.Timestamp("2026-04-20T12:00:00")
    df = anchor_application_timelines(df, timeline_end=end, seed=42)
    csv_path = tmp_path / "p.csv"
    write_audit_outputs(df, parquet_path=str(tmp_path / "p.parquet"), duckdb_csv_path=str(csv_path))
    con = duckdb.connect(str(tmp_path / "p.db"))
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)", [str(csv_path)])
    apply_ddl(con, ROOT)
    try:
        yield con
    finally:
        con.close()


def test_period_placeholders_require_date_range() -> None:
    con = duckdb.connect(":memory:")
    qm = QueryManager(con)
    with pytest.raises(ValueError, match="date_range"):
        qm.render("period_transition_edges_unique_apps", product_type=None, date_range=None)
    con.close()


def test_period_end_snapshot_sums_to_cohort(period_db: duckdb.DuckDBPyConnection) -> None:
    qm = QueryManager(period_db)
    bounds = period_db.execute(
        "SELECT CAST(MIN(timestamp) AS DATE), CAST(MAX(timestamp) AS DATE) FROM audit_logs"
    ).fetchone()
    assert bounds[0] is not None
    dr = (str(bounds[0]), str(bounds[1]))
    cohort_n = qm.run_sql(
        """
        SELECT COUNT(DISTINCT application_id)::BIGINT AS n
        FROM audit_logs
        WHERE {{PRODUCT_TYPE_FILTER}} AND {{DATE_RANGE_FILTER}}
        """,
        product_type=None,
        date_range=dr,
    ).iloc[0]["n"]
    pd_data = load_period_dashboard(qm, product_type=None, date_range=dr)
    end_sum = int(pd_data.end_snapshot["active_applications"].sum())
    assert end_sum == int(cohort_n)


def test_load_period_dashboard_runs(period_db: duckdb.DuckDBPyConnection) -> None:
    qm = QueryManager(period_db)
    dr = ("2026-04-01", "2026-04-30")
    pd_data = load_period_dashboard(qm, product_type=None, date_range=dr)
    assert "from_stage" in pd_data.transition_edges.columns
    assert "n_apps" in pd_data.transition_edges.columns
    assert pd_data.n_movers >= 0
    assert pd_data.n_arrivals >= 0
    assert pd_data.n_losses >= 0

"""Phase 3–4: cohort anchor KPI + status snapshot."""

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
from analytics.query_manager import QueryManager  # noqa: E402
from synthetic_generator import (  # noqa: E402
    anchor_application_timelines,
    generate_synthetic_audit_log,
    write_audit_outputs,
)


@pytest.fixture
def cohort_db(tmp_path: Path):
    import pandas as pd

    df = generate_synthetic_audit_log(6, seed=7, anchor_timelines=False)
    end = pd.Timestamp("2026-04-22T18:00:00")
    df = anchor_application_timelines(df, timeline_end=end, seed=7)
    csv_path = tmp_path / "c.csv"
    write_audit_outputs(df, parquet_path=str(tmp_path / "c.parquet"), duckdb_csv_path=str(csv_path))
    con = duckdb.connect(str(tmp_path / "c.db"))
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)", [str(csv_path)])
    apply_ddl(con, ROOT)
    try:
        yield con
    finally:
        con.close()


@pytest.mark.parametrize("anchor_kind", ["submitted", "enrollment", "assigned", "compliance"])
def test_cohort_queries_run(cohort_db: duckdb.DuckDBPyConnection, anchor_kind: str) -> None:
    qm = QueryManager(cohort_db)
    as_of = "2026-12-31"
    kpi = qm.run(
        "cohort_single_kpi",
        product_type=None,
        date_range=None,
        as_of_date=as_of,
        anchor_kind=anchor_kind,
    )
    assert "cohort_month" in kpi.columns
    snap = qm.run(
        "cohort_status_snapshot",
        product_type=None,
        date_range=None,
        as_of_date=as_of,
        anchor_kind=anchor_kind,
    )
    assert "step_order" in snap.columns
    ex = qm.run(
        "cohort_anchor_excluded",
        product_type=None,
        date_range=None,
        anchor_kind=anchor_kind,
    )
    assert int(ex.iloc[0]["n_excluded_no_anchor"]) >= 0


def test_cohort_requires_as_of(cohort_db: duckdb.DuckDBPyConnection) -> None:
    qm = QueryManager(cohort_db)
    with pytest.raises(ValueError, match="as_of_date"):
        qm.run(
            "cohort_single_kpi",
            product_type=None,
            date_range=None,
            as_of_date=None,
            anchor_kind="submitted",
        )

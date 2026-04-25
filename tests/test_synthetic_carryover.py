"""Synthetic carryover: period start snapshot should see mixed stages (not all step 0)."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.ddl_loader import apply_ddl  # noqa: E402
from analytics.period_dashboard import load_period_dashboard  # noqa: E402
from analytics.query_manager import QueryManager  # noqa: E402
from synthetic_generator import generate_synthetic_audit_log, write_audit_outputs  # noqa: E402


def test_carryover_yields_mixed_start_snapshot(tmp_path: Path) -> None:
    df = generate_synthetic_audit_log(
        400,
        seed=7,
        apply_carryover_for_period_demo=True,
        carryover_ratio=0.75,
    )
    csv_path = tmp_path / "carry.csv"
    write_audit_outputs(df, parquet_path=str(tmp_path / "c.parquet"), duckdb_csv_path=str(csv_path))
    con = duckdb.connect(str(tmp_path / "c.db"))
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)", [str(csv_path)])
    apply_ddl(con, ROOT)
    try:
        qm = QueryManager(con)
        pd_data = load_period_dashboard(qm, product_type=None, date_range=("2026-04-04", "2026-04-24"))
        start = pd_data.start_snapshot
        nonzero = start[start["active_applications"] > 0]
        assert (nonzero["step_order"] == 0).any(), "expected some true in-window arrivals"
        assert (nonzero["step_order"] > 0).any(), "expected carryover apps with prior mapped stage"
    finally:
        con.close()


def test_no_carryover_can_collapse_start(tmp_path: Path) -> None:
    df = generate_synthetic_audit_log(
        120,
        seed=11,
        apply_carryover_for_period_demo=False,
    )
    csv_path = tmp_path / "nocarry.csv"
    write_audit_outputs(df, parquet_path=str(tmp_path / "n.parquet"), duckdb_csv_path=str(csv_path))
    con = duckdb.connect(str(tmp_path / "n.db"))
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)", [str(csv_path)])
    apply_ddl(con, ROOT)
    try:
        qm = QueryManager(con)
        pd_data = load_period_dashboard(qm, product_type=None, date_range=("2026-04-04", "2026-04-24"))
        start = pd_data.start_snapshot
        step0 = int(start.loc[start["step_order"] == 0, "active_applications"].iloc[0])
        cohort = int(
            qm.run_sql(
                """
                SELECT COUNT(DISTINCT application_id)::BIGINT AS n
                FROM audit_logs
                WHERE {{PRODUCT_TYPE_FILTER}} AND {{DATE_RANGE_FILTER}}
                """,
                product_type=None,
                date_range=("2026-04-04", "2026-04-24"),
            ).iloc[0]["n"]
        )
        # Without carryover rewriting, anchoring tends to push most histories into the window,
        # but a small number of apps can still have prior rows depending on randomness.
        assert step0 / max(1, cohort) >= 0.90
    finally:
        con.close()

"""
Quick smoke tests: synthetic data shape, timeline anchor, DuckDB load, funnel SQL.

Run from repo root (Cursor runs this automatically after changes):
  PYTHONPATH=. pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.ddl_loader import apply_ddl  # noqa: E402
from analytics.query_manager import QueryManager  # noqa: E402
from audit_log_schema import AUDIT_COLUMNS  # noqa: E402
from synthetic_generator import (  # noqa: E402
    anchor_application_timelines,
    generate_synthetic_audit_log,
    write_audit_outputs,
)


def test_audit_columns_present() -> None:
    df = generate_synthetic_audit_log(2, seed=0, anchor_timelines=False)
    for c in AUDIT_COLUMNS:
        assert c in df.columns


def test_generate_row_counts() -> None:
    df = generate_synthetic_audit_log(3, seed=7, anchor_timelines=False)
    assert df["application_id"].nunique() == 3
    assert len(df) >= 9


def test_anchor_moves_last_event_into_window() -> None:
    df = generate_synthetic_audit_log(2, seed=3, anchor_timelines=False)
    end = pd.Timestamp("2026-04-24T18:00:00")
    anchored = anchor_application_timelines(df, timeline_end=end, seed=3)
    new_max = pd.to_datetime(anchored["timestamp"]).max()
    assert new_max <= end
    assert new_max >= end - pd.Timedelta(days=14)
    assert len(anchored) == len(df)


def test_duckdb_load_and_funnel(tmp_path: Path) -> None:
    df = generate_synthetic_audit_log(4, seed=11, anchor_timelines=True)
    csv_path = tmp_path / "synthetic_logs.csv"
    pq = tmp_path / "out.parquet"
    write_audit_outputs(df, parquet_path=str(pq), duckdb_csv_path=str(csv_path))

    db_path = tmp_path / "test.db"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("DROP TABLE IF EXISTS audit_logs;")
        con.execute(
            "CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)",
            [str(csv_path)],
        )
        n = con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        assert n == len(df)

        apply_ddl(con, ROOT)
        qm = QueryManager(con)
        funnel = qm.run("funnel_overview", product_type=None, date_range=None)
        assert len(funnel) == 34
        assert funnel["active_applications"].sum() == 4
    finally:
        con.close()


@pytest.fixture
def tiny_db(tmp_path: Path):
    df = generate_synthetic_audit_log(1, seed=99, anchor_timelines=False)
    csv_path = tmp_path / "s.csv"
    write_audit_outputs(df, parquet_path=str(tmp_path / "x.parquet"), duckdb_csv_path=str(csv_path))
    con = duckdb.connect(str(tmp_path / "t.db"))
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM read_csv_auto(?, header = true)", [str(csv_path)])
    apply_ddl(con, ROOT)
    try:
        yield con
    finally:
        con.close()


def test_application_history_filter(tiny_db: duckdb.DuckDBPyConnection) -> None:
    aid = tiny_db.execute("SELECT application_id FROM audit_logs LIMIT 1").fetchone()[0]
    qm = QueryManager(tiny_db)
    hist = qm.run("application_history", product_type=None, application_id=aid)
    assert len(hist) >= 1
    assert "action" in hist.columns

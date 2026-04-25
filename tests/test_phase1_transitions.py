"""Phase 1: v_transitions dedup + drift check vs latest stage (PHASE_0 §1 / §3)."""

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


def _apply_micro_audit(con: duckdb.DuckDBPyConnection) -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01 10:00:00", "2026-01-01 11:00:00", "2026-01-01 12:00:00"]
            ),
            "actor": ["c@x.com", "c@x.com", "ops@relio.ch"],
            "action": ["APPLICATION_STARTED", "APPLICATION_SUBMITTED", "APP_ASSIGNED"],
            "description": ["", "", ""],
            "context": [{}, {}, {}],
            "application_id": ["app-one"] * 3,
            "product_type": ["Business Account"] * 3,
        }
    )
    con.register("_tmp_audit", df)
    con.execute("CREATE TABLE audit_logs AS SELECT * FROM _tmp_audit")
    apply_ddl(con, ROOT)


def test_transitions_skip_same_stage() -> None:
    con = duckdb.connect(":memory:")
    _apply_micro_audit(con)
    try:
        n = con.execute("SELECT COUNT(*) FROM v_transitions").fetchone()[0]
        assert n == 2
        rows = con.execute(
            "SELECT from_stage, to_stage FROM v_transitions ORDER BY transition_at"
        ).fetchall()
        assert rows[0] == (1, 2)
        assert rows[1] == (2, 5)
    finally:
        con.close()


def test_transition_latest_drift_zero_on_synthetic_db() -> None:
    db = ROOT / "data" / "relio_analytics.db"
    if not db.is_file():
        pytest.skip("relio_analytics.db missing; run scripts/db_setup.py")
    con = duckdb.connect(str(db), read_only=True)
    try:
        drift = con.execute(
            (ROOT / "analytics/queries/transition_latest_drift_check.sql").read_text(encoding="utf-8")
        ).fetchone()[0]
        assert drift == 0
    finally:
        con.close()

from __future__ import annotations

from pathlib import Path

import duckdb

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


def test_sla_compliance_pct_bounds_and_counts() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("sla_compliance", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert set(df["sla_name"].unique()) <= {"CR review", "Compliance", "RFI response", "Offer issuance"}
    assert (df["n_eligible"] >= 0).all()
    assert (df["n_within"] <= df["n_eligible"]).all()
    assert (df["n_breached"] <= df["n_eligible"]).all()
    assert (df["pct_within"] >= 0.0).all()
    assert (df["pct_within"] <= 100.0).all()


def test_sla_trend_has_valid_pct_bounds() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("sla_compliance_trend", product_type=None, date_range=("2026-01-16", "2026-04-24"))
    if df.empty:
        return
    assert (df["pct_within"] >= 0.0).all()
    assert (df["pct_within"] <= 100.0).all()


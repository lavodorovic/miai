from __future__ import annotations

from pathlib import Path

import duckdb

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


def test_cohort_survival_pct_bounds() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run(
        "cohort_survival",
        product_type=None,
        date_range=None,
        as_of_date="2026-04-24",
        anchor_kind="submitted",
    )
    if df.empty:
        return
    for col in ["pct_alive_7d", "pct_alive_14d", "pct_alive_30d", "pct_alive_60d"]:
        assert (df[col] >= 0.0).all()
        assert (df[col] <= 100.0).all()


def test_cohort_time_to_offer_non_negative() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run(
        "cohort_time_to_offer",
        product_type=None,
        date_range=None,
        as_of_date="2026-04-24",
        anchor_kind="submitted",
    )
    if df.empty:
        return
    assert (df["p50_days_to_offer"] >= 0.0).all()
    assert (df["p90_days_to_offer"] >= 0.0).all()
    assert (df["p90_days_to_offer"] >= df["p50_days_to_offer"]).all()


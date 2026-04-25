from __future__ import annotations

from pathlib import Path

import duckdb

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


def test_capacity_inputs_non_negative() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("capacity_inputs", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert len(df) == 1
    row = df.iloc[0].to_dict()
    assert float(row["inflow_per_day"]) >= 0.0
    assert float(row["backlog_inflight"]) >= 0.0
    assert float(row["cycle_submit_to_terminal_p50"]) >= 0.0
    assert float(row["cycle_submit_to_offer_p50"]) >= 0.0
    assert float(row["inflight_age_p50"]) >= 0.0


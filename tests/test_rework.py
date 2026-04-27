from __future__ import annotations

from pathlib import Path

import duckdb

from analytics.query_manager import QueryManager


ROOT = Path(__file__).resolve().parent.parent


def test_rework_overview_invariants() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("rework_overview", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert len(df) == 1
    row = df.iloc[0].to_dict()
    assert row["n_apps_total"] >= row["n_apps_with_interactions"]
    assert row["n_apps_with_interactions"] >= row["n_apps_2plus_interactions"]
    assert row["n_apps_2plus_interactions"] >= row["n_apps_3plus_interactions"]
    assert 0.0 <= float(row["pct_first_pass"]) <= 100.0


def test_rework_by_product_sums_reasonably() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    overall = qm.run("rework_overview", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    byp = qm.run("rework_by_product", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert int(byp["n_apps_total"].sum()) == int(overall.iloc[0]["n_apps_total"])


def test_rework_cases_are_actionable_when_present() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    df = qm.run("rework_cases", product_type=None, date_range=("2026-04-04", "2026-04-24"))
    assert {"application_id", "n_interactions", "compliance_reopened", "primary_team"}.issubset(df.columns)


def test_rework_by_product_no_ambiguous_product_when_cohort_carries_product_type() -> None:
    """Regression: cohort includes product_type + join audit_logs AS a → use FILTER_A on ``a``."""
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    dr = ("2026-04-04", "2026-04-24")
    df = qm.run("rework_by_product", product_type="Business Account", date_range=dr)
    assert len(df) >= 1
    assert "product_type" in df.columns


def test_rework_outcome_by_loops_matches_interaction_dist() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    dr = ("2026-04-04", "2026-04-24")
    dist = qm.run("rework_interaction_dist", product_type=None, date_range=dr)
    out = qm.run("rework_outcome_by_loops", product_type=None, date_range=dr)
    assert int(dist["n_apps"].sum()) == int(out["n_apps"].sum())
    con.close()


def test_rework_interaction_dist_sums_to_cohort() -> None:
    con = duckdb.connect(str(ROOT / "data" / "relio_analytics.db"), read_only=True)
    qm = QueryManager(con)
    dr = ("2026-04-04", "2026-04-24")
    dist = qm.run("rework_interaction_dist", product_type=None, date_range=dr)
    assert {"interaction_bucket", "n_apps"}.issubset(dist.columns)
    cohort = int(
        con.execute(
            """
            SELECT COUNT(DISTINCT application_id) FROM audit_logs
            WHERE timestamp::DATE BETWEEN ? AND ?
            """,
            [dr[0], dr[1]],
        ).fetchone()[0]
    )
    assert int(dist["n_apps"].sum()) == cohort


# Analytics validation runbook

See `docs/TESTS.md` for the canonical list of **always-run** checks and **periodic** deeper checks.

## CI / pre-release

From the repository root:

```bash
python3 -m pytest tests/test_phase1_transitions.py tests/test_period_dashboard.py tests/test_ci_analytics_gates.py tests/test_cohort_queries.py -q
```

- **Transition vs latest stage:** `analytics/queries/transition_latest_drift_check.sql` must return `drift_rows = 0` (see `PHASE_0_DEFINITIONS.md` §1 / §3).
- **Period end snapshot vs cohort:** `load_period_dashboard(...)` end snapshot bar sum must equal the in-filter distinct `application_id` count for the same `product_type` + `date_range` (§2).

Full suite: `python3 -m pytest tests/ -q`.

## E2E browser check (optional but recommended before demos)

This runs a **real headless browser** against the Streamlit UI and asserts the
Period dashboard start snapshot is not collapsed.

One-time setup:

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

Run:

```bash
python3 -m pytest -q -m e2e tests/test_e2e_streamlit_period_dashboard.py
```

## Synthetic data refresh

```bash
python3 scripts/generate_synthetic_audit_log.py
python3 scripts/db_setup.py
```

By default, generation applies **timeline anchoring** (last event near `--timeline-end`) and **carryover** (~70% of apps get audit rows *before* the late-April window so the Period dashboard **start snapshot** shows a real stage mix). Use `--no-carryover` to revert to the old “all step 0 at start” behaviour. Close any process holding `data/relio_analytics.db` (e.g. Streamlit) before `db_setup.py` so DuckDB can write the file.

## Nightly (optional)

If `data/relio_analytics.db` is refreshed by ETL, run the same pytest slice or execute `transition_latest_drift_check.sql` in DuckDB after `scripts/db_setup.py`.

## Period-over-period (backlog)

Reuse `period_*` queries with a shifted `date_range` tuple; definitions stay in `PHASE_0_DEFINITIONS.md` §2.

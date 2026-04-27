# Tests (always-run + periodic)

This repo follows a strict rule: **don’t claim “done” until the UI is verified**.

The checks below are the **minimum bar** we run before any “ready” handoff.

## Always-run (every iteration)

### Logic / data contracts

Run:

```bash
python3 -m pytest -q \
  tests/test_phase1_transitions.py \
  tests/test_period_dashboard.py \
  tests/test_cohort_queries.py \
  tests/test_ci_analytics_gates.py \
  tests/test_synthetic_carryover.py \
  tests/test_views_phase2.py \
  tests/test_overview_extras.py \
  tests/test_bottleneck_radar.py \
  tests/test_rework.py \
  tests/test_team_workload.py \
  tests/test_sla_compliance.py \
  tests/test_capacity_math.py \
  tests/test_cohort_survival_and_offer.py
```

What this covers:
- Transition stream dedup + latest-stage drift must be **0**
- Period dashboard snapshots + cohort sum invariants
- Cohort anchor + KPI queries invariants
- Synthetic demo data stays “period dashboard meaningful”

### UI verification (real browser)

One-time setup:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
```

Run:

```bash
python3 -m pytest -q -m e2e tests/test_e2e_streamlit_period_dashboard.py
python3 -m pytest -q -m e2e tests/test_e2e_streamlit_bottleneck_radar.py
```

What this covers:
- Boots Streamlit on a random port
- Opens the app in **headless Chromium**
- Navigates to **Period dashboard**
- Asserts the “Start snapshot — apps with prior history” sanity metric is **> 0**

## One-command “safe to review”

If you want to refresh synthetic data + DuckDB, run all tests, then start Streamlit:

```bash
bash scripts/verify_and_setup.sh
```

## Periodic / deeper checks (run as needed)

- **Browser screenshot diff**: add Playwright screenshots when you change layout/labels.
- **Performance budgets**: time queries on representative DB sizes; fail if regressions exceed threshold.
- **Cross-anchor consistency**: verify cohort sizes and excluded counts across anchors on a fixed dataset.
- **Timezone migration**: run parallel “naive” vs “tz-aware” comparisons during the migration window.


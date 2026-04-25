## Session report (auto)

### What changed
- **Foundational views**
  - Added `v_team` and `v_stage_dwell` views for team attribution and stage dwell facts.
- **Synthetic data realism**
  - Synthetic generator now produces **8 CR + 8 Compliance** actors with sticky assignment + light reassignment noise.
- **New/updated dashboards**
  - Executive overview: swimlane funnel, who-has-the-ball, throughput (MA7), SLA status buckets, enriched watchlist.
  - New tabs: **Bottleneck radar**, **Rework analytics**, **Team workload**, **SLA compliance**, **Capacity what-if**.
  - Cohort analytics: survival (+7/+14/+30/+60) and time-to-first-offer (p50/p90).
  - App investigator: per-application **time-in-stage** bar chart (hours).

### Tests
- Unit tests: expanded suite includes new invariants for views, overview extras, bottleneck/rework/team/SLA/capacity math, cohort survival/time-to-offer.
- Browser E2E:
  - `tests/test_e2e_streamlit_period_dashboard.py`
  - `tests/test_e2e_streamlit_bottleneck_radar.py`

### Notes / TODOs
- No known failing tests at the end of the run.
- Repo is not currently a git repository, so changes are uncommitted by design.


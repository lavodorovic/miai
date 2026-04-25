# Phase 0 — Definitions (Eng + PM)

Single source of truth for analytics SQL and Streamlit UI. If something is not defined here, treat it as **undefined** until this doc is updated.

---

## 1. Stage list and order

**Source of truth (v0):** `step_order` 1–34 and `step_label` text in `analytics/queries/funnel_overview.sql` (dimension) plus the **same** `action → stage_order` mapping in DuckDB view **`v_audit_staged`** (`analytics/ddl/01_v_audit_staged.sql`). `funnel_overview` reads `stage_order` from `v_audit_staged`; do not duplicate the CASE elsewhere without updating both (§6).

**Meaning:** A row is a **stage bucket** for reporting. An application’s **current stage** is derived only from its **latest** `audit_logs` row (by `timestamp`, tie-break `action`), mapped through the `CASE` in that query to one `step_order`.

**Order:** `step_order` ascending is the canonical **process order** (intake → review / interaction → offer → post-accept → terminals). It is **not** guaranteed that every real journey visits every stage; order is for **display and comparison**, not proof of traversal.

**Future:** If production introduces a `state` or `transition` table, this list should be regenerated from that model and versioned (e.g. `STAGES_V2.md`).

---

## 2. Period (filters)

| Concept | Definition |
|--------|----------------|
| **Field filtered** | `audit_logs.timestamp` (naive `TIMESTAMP`; no `TIMESTAMPTZ` in v0 CSV/DuckDB load). |
| **Bounds** | **Inclusive** on both ends: `timestamp::DATE BETWEEN DATE '<start>' AND DATE '<end>'`. |
| **Timezone** | **Unspecified / naive** in v0. Treat all values as **local wall clock** unless a column is later migrated to `TIMESTAMPTZ` with an explicit policy (e.g. “stored UTC”). Document migration in this file when it happens. |
| **Cohort vs clip** | A **cohort** is “any `application_id` with ≥1 row in the period + product filter.” Downstream metrics that need **full history** (e.g. latest stage) still use **all** `audit_logs` rows for those IDs (with the same `product_type` filter where applicable), not only rows inside the date window. |

---

## 3. Transition (target schema)

v0 **does not** store transitions as first-class rows. We infer “movement” only by **ordering** `audit_logs` by time.

**Target event schema** (for a future `transitions` table or stream):

| Field | Type | Required | Notes |
|--------|------|----------|--------|
| `application_id` | UUID / string | Yes | Same as `audit_logs.application_id`. |
| `from_stage` | string or int | Yes | Previous canonical stage id/label; null only for first-ever event if we model “birth”. |
| `to_stage` | string or int | Yes | Stage after the event. |
| `at` | timestamp | Yes | Instant of transition; same timezone policy as §2. *(DuckDB view `v_transitions` names this column `transition_at` because `at` is reserved.)* |
| `reason` | string | No | e.g. `customer_reply`, `ops_ack`, `system_job`. |

**Rule:** One **logical** transition may still emit **multiple** `audit_logs` rows in the same second; transitions should either collapse to one row per **state change** or document “one row per audit row” explicitly.

---

## 4. Cohort anchors (four anchors + fallbacks)

Used for phrases like “applications **submitted** in Q1” vs “**first assigned** in Q1.”

| Anchor | Exact definition (v0) | Fallback / exclusion |
|--------|-------------------------|-------------------------|
| **1. Submitted (default cohort)** | First `timestamp` where `action = 'APPLICATION_SUBMITTED'` for the `application_id`. | If missing: **exclude** from “submitted cohort” metrics *or* bucket label **`no_submit_event`** (choose one globally; v0 SQL uses “has row in filter window” as cohort, not strict submit). **PM call:** tighten cohort to require `APPLICATION_SUBMITTED` when reporting “submitted pipeline.” |
| **2. Enrollment** | First `timestamp` where `action = 'ENROLLMENT_APPROVED'`. | If missing: **exclude** from “enrolled cohort” **or** label **`pending_enrollment`**. Do not silently substitute `MASTER_DATA_SUBMITTED`. |
| **3. First assigned (ops)** | First `timestamp` where `action IN ('ACCOUNT_MANAGER_ASSIGNED','APP_ASSIGNED')` (use earliest of the two if both exist). | If missing: **`pending_assignment`** bucket or exclude from “assigned cohort.” |
| **4. Fourth anchor (optional)** | **First compliance touch:** first `timestamp` where `action = 'COMPLIANCE_REVIEW_STARTED'`. | If missing: **`pre_compliance`** or exclude from “entered compliance” cohort. |

**Default narrative:** Unless a KPI says otherwise, **“cohort”** in the UI = anchor **#1 Submitted** once we align SQL; today’s DuckDB queries use **“any activity in date window”** as a stand-in — see §5.

---

## 5. KPI glossary (unit, anchor, as_of vs during)

| KPI / label (UI) | **Unit** | **Anchor** | **As of** vs **During** | Notes |
|-------------------|----------|------------|-------------------------|--------|
| **In filter (cohort)** | **Application** | Any row in `audit_logs` matching `product_type` + date window. | **During** window (inclusive dates). | Count distinct `application_id`. |
| **In-flight (not finished)** | **Application** | Same cohort; latest `action` **not** in terminal set: `MASTER_DATA_SUBMITTED`, `APPLICATION_REJECTED`, `APPLICATION_CANCELLED`, `OFFER_REFUSED`. | **As of** “now” (`current_timestamp`) for latest row; cohort still gated by **during** window for membership. | Terminal list is product-specific; extend in one place. |
| **Avg. processing time (days)** | **Application** (one number per app, then averaged) | Cohort membership **during** window; span = first `APPLICATION_SUBMITTED` → **max(timestamp)** over **full** history for that app (filtered by `product_type`). | Mixed: cohort **during**; span endpoints can lie outside window. | If no submit event: exclude app from average or document NaN handling. |
| **% stuck > 48h (in-flight)** | **Application** | Numerator: distinct apps on **stuck** list (`stuck_applications.sql`). Denominator: **In filter** count. | **As of** `current_timestamp` vs last event; stuck definition uses **latest** event **> 48h** old. | Stuck list excludes terminals; aligns with in-flight spirit. |
| **Funnel — latest stage** | **Application** per bar | Latest `audit_logs` row → `funnel_overview` `CASE` → one bar. | **As of** now (latest row); cohort membership **during** window. | Sum of bar heights = **In filter** if each app maps to exactly one stage. |
| **Funnel — swimlanes (collapsed)** | **Application** per bar | Latest stage mapped to a swimlane (derived from canonical stage_order). | **As of** now; cohort membership **during** window. | Operational summary view (intake/assignment/CR/compliance/interaction/offer/terminal). |
| **Who has the ball** | **Application** | Latest audit row’s `team` (from `v_team`) among in-flight cohort apps. | **As of** now; cohort membership **during** window. | Used to split “waiting on customer” vs internal teams. |
| **Throughput — terminal per day (MA7)** | **Terminal application** | Terminal actions per calendar day in window. | **During** window. | Daily terminal outcomes + 7-day moving average. |
| **SLA breach (overview)** | **Application** | In-flight apps bucketed by SLA area + ok/at-risk/breached based on hours since last event. | **As of** now; cohort membership **during** window. | Thresholds in SQL (v0): CR 24h, Compliance 48h, RFI 72h (only when last action is INTERACTION_STARTED), Offer 5d. |
| **Watchlist rows** | **Application** (one row per app) | Same as stuck query; includes `case_owner` / `latest_actor`. | **As of** now. | Sorted by `latest_at` ASC (oldest first). |
| **Period — start snapshot** | **Application** (one bucket each) | Same cohort as **In filter** for the selected window. | **As of** instant before period start: latest stage from rows with `timestamp::DATE` **strictly less than** period start date (naive §2). | `step_order = 0` = no prior product-filtered row before start (see `period_start_snapshot.sql`). |
| **Period — end snapshot** | **Application** | Same cohort. | **As of** period end: latest stage from rows with `timestamp::DATE` **≤** period end date. | Sum of bar heights = cohort size. |
| **Period — arrivals** | **Application** | Cohort member whose **first** product-filtered audit calendar day lies in `[start, end]` (inclusive). | **During** window. | Distinct from “no prior before start” when history exists outside the window. |
| **Period — losses** | **Application** | Cohort member with ≥1 terminal row (`MASTER_DATA_SUBMITTED`, `APPLICATION_REJECTED`, `APPLICATION_CANCELLED`, `OFFER_REFUSED`) whose `timestamp::DATE` is in `[start, end]`. | **During** window. | Count distinct applications. |
| **Period — transition matrix** | **Application-edge** (unique apps per from→to) | Same cohort; `v_transitions` rows with `transition_at::DATE` in `[start, end]`, aggregated by edge. | **During** window on transition timestamp. | For each `(from_stage,to_stage)`, count distinct `application_id` that experienced that edge at least once in-window. |
| **Cohort — single KPI (% in-flight)** | **Application** | Cohort month = calendar month of first anchor timestamp (§4); only apps with non-null anchor and `anchor::DATE ≤ as_of`. | **As of** selected calendar day (`timestamp::DATE ≤ as_of`, naive). | Anchor columns from `cohort_single_kpi.sql`; missing anchor = excluded (pending buckets are a §4 PM extension). |
| **Cohort — status snapshot** | **Application** (aggregated counts) | Same cohort rule as single KPI. | **As of** same date. | Long-format counts by `(cohort_month, step_order)` for distribution / pivot (`cohort_status_snapshot.sql`). |
| **Bottleneck radar** | **Stage (plus derived metrics)** | Stage-level metrics computed over in-filter cohort + last-7-days-of-window flows. | Mixed: WIP/aging **as of now**, flows/dwell **during** window. | Ranks canonical stages by composite score (WIP + net inflow + p90 dwell); used for triage. |
| **Rework analytics** | **Application** | Cohort apps aggregated for loop counts and reopened compliance. | Mixed (cohort during; counts over full history for cohort apps). | Interaction loops = count of `INTERACTION_STARTED`. Compliance reopened = `LABEL_ADDED` then later `COMPLIANCE_REVIEW_STARTED`. |
| **Team workload** | **Actor** | Actors classified as CR/Compliance via `v_team`. | Mixed: open cases **as of now**, completed **during** last 7/30 days of window. | Open cases = latest actor of in-flight app. Effort proxy uses median minutes between consecutive actor actions per app. |
| **SLA compliance** | **Application** | SLA spans measured from defined start action to end action (or now if open). | **During** window (eligibility by start event date), evaluated as-of now for open spans. | v0 SLAs in SQL: CR 24h, Compliance 48h, RFI 72h, Offer issuance 5d. |
| **Capacity what-if** | **Derived projection** | Uses inflow (submitted/day), in-flight backlog, and a cycle-time proxy. | N/A (model/projection) | Little’s Law \(WIP \approx throughput \times cycle\_time\) + linear FTE scaling assumption. |
| **Cohort survival** | **Application** | Alive = not terminal by +N days after anchor. | **As of** selected date (cohort definition) | Reports % alive at +7/+14/+30/+60 by cohort month. |
| **Cohort time-to-offer** | **Application** | Days from cohort anchor to first `OFFER_SENT`. | **As of** selected date (cohort definition) | Reports p50/p90 by cohort month. |

**“As of”** = snapshot using latest state at query time. **“During”** = restrict which events (or which apps’ activity) fall inside the reporting window.

---

## 6. Change control

- Any new KPI or chart must add a row to §5 and, if needed, a row to §4.
- Any change to stage order or `CASE` mapping must update §1 and the referenced SQL in the same PR.

*Version: v0 — aligned with MilAI synthetic pipeline + DuckDB `audit_logs` as of Phase 0.*

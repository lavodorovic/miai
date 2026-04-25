-- Capacity helper inputs:
--   - inflow_per_day: submitted apps per day (7d moving average) over last 7 days of selected window
--   - backlog_inflight: current in-flight count (as-of now), cohort gated by window + product
--   - cycle_submit_to_terminal_p50: median days from submit -> terminal (completed apps only)
--   - cycle_submit_to_offer_p50: median days from submit -> first OFFER_SENT (apps with offer only)
--   - inflight_age_p50: median days since submit for currently in-flight apps (age)

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
last7 AS (
    SELECT
        ({{PERIOD_END_DATE}} - INTERVAL 6 DAY) AS d0,
        {{PERIOD_END_DATE}} AS d1
),
inflow AS (
    SELECT
        COUNT(DISTINCT application_id)::DOUBLE / 7.0 AS inflow_per_day
    FROM audit_logs
    CROSS JOIN last7 AS w
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND action = 'APPLICATION_SUBMITTED'
      AND timestamp::DATE BETWEEN w.d0 AND w.d1
),
latest AS (
    SELECT
        a.application_id,
        arg_max(a.action, a.timestamp) AS last_action
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY a.application_id
),
backlog AS (
    SELECT COUNT(*)::BIGINT AS backlog_inflight
    FROM latest
    WHERE last_action NOT IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
),
submitted AS (
    SELECT
        c.application_id,
        MIN(CASE WHEN a.action = 'APPLICATION_SUBMITTED' THEN a.timestamp END) AS submitted_at
    FROM cohort AS c
    INNER JOIN audit_logs AS a ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY c.application_id
),
terminal AS (
    SELECT
        c.application_id,
        MIN(CASE WHEN a.action IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED') THEN a.timestamp END) AS terminal_at
    FROM cohort AS c
    INNER JOIN audit_logs AS a ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY c.application_id
),
offer AS (
    SELECT
        c.application_id,
        MIN(CASE WHEN a.action = 'OFFER_SENT' THEN a.timestamp END) AS offer_at
    FROM cohort AS c
    INNER JOIN audit_logs AS a ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY c.application_id
),
cycle_terminal AS (
    SELECT
        MEDIAN(date_diff('day', s.submitted_at, t.terminal_at))::DOUBLE AS cycle_submit_to_terminal_p50
    FROM submitted AS s
    INNER JOIN terminal AS t USING (application_id)
    WHERE s.submitted_at IS NOT NULL
      AND t.terminal_at IS NOT NULL
      AND s.submitted_at <= t.terminal_at
      AND t.terminal_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
),
cycle_offer AS (
    SELECT
        MEDIAN(date_diff('day', s.submitted_at, o.offer_at))::DOUBLE AS cycle_submit_to_offer_p50
    FROM submitted AS s
    INNER JOIN offer AS o USING (application_id)
    WHERE s.submitted_at IS NOT NULL
      AND o.offer_at IS NOT NULL
      AND s.submitted_at <= o.offer_at
      AND o.offer_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
),
inflight_age AS (
    SELECT
        MEDIAN(date_diff('day', s.submitted_at, current_timestamp))::DOUBLE AS inflight_age_p50
    FROM submitted AS s
    INNER JOIN latest AS l USING (application_id)
    WHERE s.submitted_at IS NOT NULL
      AND l.last_action NOT IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
)
SELECT
    (SELECT inflow_per_day FROM inflow) AS inflow_per_day,
    (SELECT backlog_inflight FROM backlog) AS backlog_inflight,
    COALESCE((SELECT cycle_submit_to_terminal_p50 FROM cycle_terminal), 0.0) AS cycle_submit_to_terminal_p50,
    COALESCE((SELECT cycle_submit_to_offer_p50 FROM cycle_offer), 0.0) AS cycle_submit_to_offer_p50,
    COALESCE((SELECT inflight_age_p50 FROM inflight_age), 0.0) AS inflight_age_p50;


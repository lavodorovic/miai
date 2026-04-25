-- SLA compliance trend by week (pct within).
-- Week is based on the SLA start event date (eligible rows).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
events AS (
    SELECT
        a.application_id,
        a.action,
        a.timestamp
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
),
cr AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'CUSTOMER_RELATION_REVIEW_STARTED' THEN timestamp END) AS start_at,
        MIN(CASE WHEN action = 'CUSTOMER_RELATION_REVIEW_COMPLETED' THEN timestamp END) AS end_at
    FROM events
    GROUP BY application_id
),
compliance AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'COMPLIANCE_REVIEW_STARTED' THEN timestamp END) AS start_at,
        MIN(CASE WHEN action = 'COMPLIANCE_REVIEW_COMPLETED' THEN timestamp END) AS end_at
    FROM events
    GROUP BY application_id
),
rfi AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'INTERACTION_STARTED' THEN timestamp END) AS start_at,
        MIN(CASE WHEN action = 'INTERACTION_SUBMITTED' THEN timestamp END) AS end_at
    FROM events
    GROUP BY application_id
),
offer AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'COMPLIANCE_REVIEW_COMPLETED' THEN timestamp END) AS start_at,
        MIN(CASE WHEN action = 'OFFER_SENT' THEN timestamp END) AS end_at
    FROM events
    GROUP BY application_id
),
unioned AS (
    SELECT 'CR review' AS sla_name, 24.0 AS threshold_hours, application_id, start_at, end_at FROM cr
    UNION ALL
    SELECT 'Compliance' AS sla_name, 48.0 AS threshold_hours, application_id, start_at, end_at FROM compliance
    UNION ALL
    SELECT 'RFI response' AS sla_name, 72.0 AS threshold_hours, application_id, start_at, end_at FROM rfi
    UNION ALL
    SELECT 'Offer issuance' AS sla_name, 120.0 AS threshold_hours, application_id, start_at, end_at FROM offer
),
eligible AS (
    SELECT
        sla_name,
        threshold_hours,
        application_id,
        start_at,
        end_at,
        DATE_TRUNC('week', start_at)::DATE AS week_start,
        CASE
            WHEN start_at IS NULL THEN NULL
            WHEN end_at IS NULL THEN (EXTRACT(EPOCH FROM (current_timestamp - start_at)) / 3600.0)
            ELSE (EXTRACT(EPOCH FROM (end_at - start_at)) / 3600.0)
        END AS elapsed_hours
    FROM unioned
    WHERE start_at IS NOT NULL
      AND start_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
)
SELECT
    CAST(week_start AS VARCHAR) AS week,
    sla_name,
    (100.0 * SUM(CASE WHEN elapsed_hours <= threshold_hours THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0))::DOUBLE AS pct_within
FROM eligible
GROUP BY week, sla_name
ORDER BY week, sla_name;


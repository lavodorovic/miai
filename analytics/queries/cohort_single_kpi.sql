-- Phase 3 — Single KPI by cohort month (PHASE_0 §4 anchors + §5 as-of).
-- Cohort: applications with non-null {{ANCHOR_TS}} and anchor calendar day <= {{AS_OF_DATE}} (exclude pending).
-- One row per application in enriched CTE; KPI = % still in-flight (latest row as-of date not terminal).

WITH anchors AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'APPLICATION_SUBMITTED' THEN timestamp END) AS anchor_submitted,
        MIN(CASE WHEN action = 'ENROLLMENT_APPROVED' THEN timestamp END) AS anchor_enrollment,
        MIN(CASE WHEN action IN ('ACCOUNT_MANAGER_ASSIGNED', 'APP_ASSIGNED') THEN timestamp END) AS anchor_assigned,
        MIN(CASE WHEN action = 'COMPLIANCE_REVIEW_STARTED' THEN timestamp END) AS anchor_compliance
    FROM v_audit_staged
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY application_id
),
cohort AS (
    SELECT
        application_id,
        CAST(date_trunc('month', CAST({{ANCHOR_TS}} AS DATE)) AS DATE) AS cohort_month
    FROM anchors
    WHERE {{ANCHOR_TS}} IS NOT NULL
      AND CAST({{ANCHOR_TS}} AS DATE) <= {{AS_OF_DATE}}
),
latest AS (
    SELECT
        s.application_id,
        s.stage_order,
        s.action
    FROM v_audit_staged AS s
    INNER JOIN cohort AS c ON s.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND s.timestamp::DATE <= {{AS_OF_DATE}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY s.application_id
        ORDER BY s.timestamp DESC, s.action DESC
    ) = 1
),
enriched AS (
    SELECT
        c.cohort_month,
        c.application_id,
        l.stage_order,
        l.action NOT IN (
            'MASTER_DATA_SUBMITTED',
            'APPLICATION_REJECTED',
            'APPLICATION_CANCELLED',
            'OFFER_REFUSED'
        ) AS in_flight
    FROM cohort AS c
    INNER JOIN latest AS l ON l.application_id = c.application_id
)
SELECT
    cohort_month,
    COUNT(*)::BIGINT AS n_applications,
    ROUND(100.0 * AVG(CASE WHEN in_flight THEN 1.0 ELSE 0.0 END), 2)::DOUBLE AS pct_in_flight_as_of
FROM enriched
GROUP BY cohort_month
ORDER BY cohort_month;

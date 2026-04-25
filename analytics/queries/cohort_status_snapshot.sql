-- Phase 4 — As-of distribution of latest stage_order by cohort month (same anchors/cohort as cohort_single_kpi).
-- Long format: cohort_month, step_order, n_applications (for pivot / heatmap in UI).

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
        s.stage_order
    FROM v_audit_staged AS s
    INNER JOIN cohort AS c ON s.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND s.timestamp::DATE <= {{AS_OF_DATE}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY s.application_id
        ORDER BY s.timestamp DESC, s.action DESC
    ) = 1
)
SELECT
    c.cohort_month,
    l.stage_order AS step_order,
    COUNT(*)::BIGINT AS n_applications
FROM cohort AS c
INNER JOIN latest AS l ON l.application_id = c.application_id
GROUP BY c.cohort_month, l.stage_order
ORDER BY c.cohort_month, l.stage_order;

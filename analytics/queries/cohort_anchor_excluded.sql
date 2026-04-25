-- Count distinct applications with product-filtered audit rows but NULL selected anchor (§4 pending / excluded).
-- Uses same anchor columns as cohort_single_kpi; does not require as-of or date window.

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
)
SELECT COUNT(*)::BIGINT AS n_excluded_no_anchor
FROM anchors
WHERE {{ANCHOR_TS}} IS NULL;

-- Cohort time-to-offer (median, p90) by cohort month.
-- Cohort month uses selected anchor ({{ANCHOR_TS}}) per PHASE_0 §4.
-- Time-to-offer = days from anchor timestamp to first OFFER_SENT.

WITH anchors AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'APPLICATION_SUBMITTED' THEN timestamp END) AS anchor_submitted,
        MIN(CASE WHEN action = 'ENROLLMENT_APPROVED' THEN timestamp END) AS anchor_enrollment,
        MIN(CASE WHEN action IN ('ACCOUNT_MANAGER_ASSIGNED','APP_ASSIGNED') THEN timestamp END) AS anchor_assigned,
        MIN(CASE WHEN action = 'COMPLIANCE_REVIEW_STARTED' THEN timestamp END) AS anchor_compliance
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY application_id
),
cohort AS (
    SELECT
        anchors.application_id,
        {{ANCHOR_TS}} AS anchor_ts,
        DATE_TRUNC('month', {{ANCHOR_TS}})::DATE AS cohort_month
    FROM anchors
    WHERE {{ANCHOR_TS}} IS NOT NULL
      AND {{ANCHOR_TS}}::DATE <= {{AS_OF_DATE}}
),
offers AS (
    SELECT
        application_id,
        MIN(timestamp) AS first_offer_at
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND action = 'OFFER_SENT'
    GROUP BY application_id
),
joined AS (
    SELECT
        c.cohort_month,
        date_diff('day', c.anchor_ts, o.first_offer_at)::DOUBLE AS days_to_offer
    FROM cohort AS c
    INNER JOIN offers AS o USING (application_id)
    WHERE o.first_offer_at IS NOT NULL
      AND c.anchor_ts IS NOT NULL
      AND o.first_offer_at >= c.anchor_ts
)
SELECT
    cohort_month,
    COUNT(*)::BIGINT AS n_with_offer,
    MEDIAN(days_to_offer) AS p50_days_to_offer,
    QUANTILE_CONT(days_to_offer, 0.90) AS p90_days_to_offer
FROM joined
GROUP BY cohort_month
ORDER BY cohort_month;


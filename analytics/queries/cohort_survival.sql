-- Cohort survival snapshots: % still in-flight at +7/+14/+30/+60 days after anchor.
-- Uses selected anchor ({{ANCHOR_TS}}) per PHASE_0 §4.

WITH anchors AS (
    SELECT
        application_id,
        MIN(CASE WHEN action = 'APPLICATION_SUBMITTED' THEN timestamp END) AS anchor_submitted,
        MIN(CASE WHEN action = 'ENROLLMENT_APPROVED' THEN timestamp END) AS anchor_enrollment,
        MIN(CASE WHEN action IN ('ACCOUNT_MANAGER_ASSIGNED','APP_ASSIGNED') THEN timestamp END) AS anchor_assigned,
        MIN(CASE WHEN action = 'COMPLIANCE_REVIEW_STARTED' THEN timestamp END) AS anchor_compliance
    FROM v_audit_staged
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
terminal AS (
    SELECT
        s.application_id,
        MIN(s.timestamp) AS terminal_at
    FROM v_audit_staged AS s
    INNER JOIN cohort AS c ON c.application_id = s.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND action IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
      AND s.timestamp >= c.anchor_ts
      AND s.timestamp::DATE <= {{AS_OF_DATE}}
    GROUP BY s.application_id
),
joined AS (
    SELECT
        c.cohort_month,
        c.application_id,
        c.anchor_ts,
        t.terminal_at
    FROM cohort AS c
    LEFT JOIN terminal AS t USING (application_id)
),
eligible AS (
    SELECT
        cohort_month,
        application_id,
        anchor_ts,
        terminal_at,
        (anchor_ts + INTERVAL 7 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_7d,
        (anchor_ts + INTERVAL 14 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_14d,
        (anchor_ts + INTERVAL 30 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_30d,
        (anchor_ts + INTERVAL 60 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_60d
    FROM joined
)
SELECT
    cohort_month,
    COUNT(*)::BIGINT AS n_apps,
    COALESCE((100.0 * SUM(
        CASE
            WHEN eligible_7d AND (terminal_at IS NULL OR terminal_at > (anchor_ts + INTERVAL 7 DAY)) THEN 1
            ELSE 0
        END
    ) / NULLIF(SUM(CASE WHEN eligible_7d THEN 1 ELSE 0 END), 0))::DOUBLE, 0.0) AS pct_alive_7d,
    COALESCE((100.0 * SUM(
        CASE
            WHEN eligible_14d AND (terminal_at IS NULL OR terminal_at > (anchor_ts + INTERVAL 14 DAY)) THEN 1
            ELSE 0
        END
    ) / NULLIF(SUM(CASE WHEN eligible_14d THEN 1 ELSE 0 END), 0))::DOUBLE, 0.0) AS pct_alive_14d,
    COALESCE((100.0 * SUM(
        CASE
            WHEN eligible_30d AND (terminal_at IS NULL OR terminal_at > (anchor_ts + INTERVAL 30 DAY)) THEN 1
            ELSE 0
        END
    ) / NULLIF(SUM(CASE WHEN eligible_30d THEN 1 ELSE 0 END), 0))::DOUBLE, 0.0) AS pct_alive_30d,
    COALESCE((100.0 * SUM(
        CASE
            WHEN eligible_60d AND (terminal_at IS NULL OR terminal_at > (anchor_ts + INTERVAL 60 DAY)) THEN 1
            ELSE 0
        END
    ) / NULLIF(SUM(CASE WHEN eligible_60d THEN 1 ELSE 0 END), 0))::DOUBLE, 0.0) AS pct_alive_60d
FROM eligible
GROUP BY cohort_month
ORDER BY cohort_month;


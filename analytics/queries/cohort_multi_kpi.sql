-- Combined cohort KPI table (single wide table by cohort month).
-- Aligns definitions with PHASE_0 §4–§5: anchor-based cohort, as-of snapshots, and survival horizons.

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
        anchors.application_id,
        {{ANCHOR_TS}} AS anchor_ts,
        DATE_TRUNC('month', {{ANCHOR_TS}})::DATE AS cohort_month
    FROM anchors
    WHERE {{ANCHOR_TS}} IS NOT NULL
      AND {{ANCHOR_TS}}::DATE <= {{AS_OF_DATE}}
),
latest_asof AS (
    SELECT
        s.application_id,
        s.action
    FROM v_audit_staged AS s
    INNER JOIN cohort AS c ON c.application_id = s.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND s.timestamp::DATE <= {{AS_OF_DATE}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY s.application_id
        ORDER BY s.timestamp DESC, s.action DESC
    ) = 1
),
inflight AS (
    SELECT
        c.cohort_month,
        COUNT(*)::BIGINT AS n_apps,
        ROUND(
            100.0 * AVG(
                CASE WHEN l.action NOT IN (
                    'MASTER_DATA_SUBMITTED',
                    'APPLICATION_REJECTED',
                    'APPLICATION_CANCELLED',
                    'OFFER_REFUSED'
                ) THEN 1.0 ELSE 0.0 END
            ),
            2
        )::DOUBLE AS pct_in_flight_as_of
    FROM cohort AS c
    INNER JOIN latest_asof AS l USING (application_id)
    GROUP BY c.cohort_month
),
terminal AS (
    SELECT
        s.application_id,
        MIN(s.timestamp) AS terminal_at
    FROM v_audit_staged AS s
    INNER JOIN cohort AS c ON c.application_id = s.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND s.action IN ('MASTER_DATA_SUBMITTED','APPLICATION_REJECTED','APPLICATION_CANCELLED','OFFER_REFUSED')
      AND s.timestamp >= c.anchor_ts
      AND s.timestamp::DATE <= {{AS_OF_DATE}}
    GROUP BY s.application_id
),
survival_base AS (
    SELECT
        c.cohort_month,
        c.application_id,
        c.anchor_ts,
        t.terminal_at,
        (c.anchor_ts + INTERVAL 7 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_7d,
        (c.anchor_ts + INTERVAL 14 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_14d,
        (c.anchor_ts + INTERVAL 30 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_30d,
        (c.anchor_ts + INTERVAL 60 DAY) <= ({{AS_OF_DATE}}::TIMESTAMP) AS eligible_60d
    FROM cohort AS c
    LEFT JOIN terminal AS t USING (application_id)
),
survival AS (
    SELECT
        cohort_month,
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
    FROM survival_base
    GROUP BY cohort_month
),
offers AS (
    SELECT
        s.application_id,
        MIN(s.timestamp) AS first_offer_at
    FROM v_audit_staged AS s
    INNER JOIN cohort AS c ON c.application_id = s.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND s.action = 'OFFER_SENT'
      AND s.timestamp >= c.anchor_ts
      AND s.timestamp::DATE <= {{AS_OF_DATE}}
    GROUP BY s.application_id
),
time_to_offer AS (
    SELECT
        c.cohort_month,
        COUNT(*)::BIGINT AS n_with_offer,
        MEDIAN(date_diff('day', c.anchor_ts, o.first_offer_at)::DOUBLE) AS p50_days_to_offer,
        QUANTILE_CONT(date_diff('day', c.anchor_ts, o.first_offer_at)::DOUBLE, 0.90) AS p90_days_to_offer
    FROM cohort AS c
    INNER JOIN offers AS o USING (application_id)
    WHERE o.first_offer_at IS NOT NULL
      AND o.first_offer_at >= c.anchor_ts
    GROUP BY c.cohort_month
)
SELECT
    i.cohort_month,
    i.n_apps,
    i.pct_in_flight_as_of,
    s.pct_alive_7d,
    s.pct_alive_14d,
    s.pct_alive_30d,
    s.pct_alive_60d,
    t.n_with_offer,
    t.p50_days_to_offer,
    t.p90_days_to_offer
FROM inflight AS i
LEFT JOIN survival AS s USING (cohort_month)
LEFT JOIN time_to_offer AS t USING (cohort_month)
ORDER BY i.cohort_month;


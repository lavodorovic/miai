-- Daily arrivals and losses within the period window (naive dates).
-- Arrivals: cohort apps whose first product-filtered audit day equals each calendar day in [start,end].
-- Losses: distinct cohort apps with a terminal action on that calendar day (can count a loss once per day).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
first_seen AS (
    SELECT
        application_id,
        MIN(timestamp)::DATE AS first_day
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY application_id
),
arrivals AS (
    SELECT
        f.first_day AS day,
        COUNT(*)::BIGINT AS n
    FROM cohort AS c
    INNER JOIN first_seen AS f ON f.application_id = c.application_id
    WHERE f.first_day BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
    GROUP BY 1
),
losses AS (
    SELECT
        a.timestamp::DATE AS day,
        COUNT(DISTINCT a.application_id)::BIGINT AS n
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON c.application_id = a.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND a.timestamp::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
      AND a.action IN (
          'MASTER_DATA_SUBMITTED',
          'APPLICATION_REJECTED',
          'APPLICATION_CANCELLED',
          'OFFER_REFUSED'
      )
    GROUP BY 1
)
SELECT 'arrivals' AS series, day, n FROM arrivals
UNION ALL
SELECT 'losses' AS series, day, n FROM losses
ORDER BY day, series;

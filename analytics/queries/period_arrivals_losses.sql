-- In-period arrivals & losses (PHASE_0 §2 naive dates, inclusive BETWEEN on calendar days).
-- Arrivals: cohort apps whose first product-filtered audit day falls inside [start,end].
-- Losses: cohort apps with a terminal action (same set as §5 in-flight exclusion) on any row
--   with timestamp::DATE inside [start,end] (per application once).

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
    SELECT COUNT(*)::BIGINT AS n
    FROM cohort AS c
    INNER JOIN first_seen AS f ON f.application_id = c.application_id
    WHERE f.first_day BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
),
losses AS (
    SELECT
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
)
SELECT
    (SELECT n FROM arrivals) AS n_arrivals,
    (SELECT n FROM losses) AS n_losses;

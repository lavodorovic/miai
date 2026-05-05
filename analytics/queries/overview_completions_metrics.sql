-- Cases completed (terminal) in trailing 30 days + change vs 90-day trend.
-- Trend = pace implied by terminal completions in the 90 calendar days *before* the last-30d window
--   (i.e. days [ref_d - 119, ref_d - 30] inclusive): expected count for a 30-day stretch = total_90 / 3.

WITH ref AS (
    SELECT max(timestamp)::DATE AS ref_d
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
),
bounds AS (
    SELECT
        ref_d,
        ref_d - INTERVAL '29 DAY' AS last30_start,
        ref_d AS last30_end,
        ref_d - INTERVAL '119 DAY' AS prior90_start,
        ref_d - INTERVAL '30 DAY' AS prior90_end
    FROM ref
),
terminal AS (
    SELECT DISTINCT application_id, timestamp::DATE AS d
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
      AND action IN (
          'MASTER_DATA_SUBMITTED',
          'APPLICATION_REJECTED',
          'APPLICATION_CANCELLED',
          'OFFER_REFUSED'
      )
),
cnt AS (
    SELECT
        (
            SELECT COUNT(DISTINCT application_id)
            FROM terminal
            CROSS JOIN bounds AS b
            WHERE d BETWEEN b.last30_start AND b.last30_end
        )::DOUBLE AS n_last_30d,
        (
            SELECT COUNT(DISTINCT application_id)
            FROM terminal
            CROSS JOIN bounds AS b
            WHERE d BETWEEN b.prior90_start AND b.prior90_end
        )::DOUBLE AS n_prior_90d
    FROM bounds
)
SELECT
    n_last_30d::BIGINT AS n_completed_last_30d,
    (n_prior_90d / 3.0) AS trend_30d_from_90d_pace,
    CASE
        WHEN n_prior_90d > 0 THEN
            (
                (n_last_30d - (n_prior_90d / 3.0))
                / (n_prior_90d / 3.0)
            ) * 100.0
        ELSE NULL
    END AS pct_change_vs_90d_trend
FROM cnt;

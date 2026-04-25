-- Throughput: terminal events per day (during date window).
-- Returns daily count + 7-day moving average.

WITH daily AS (
    SELECT
        timestamp::DATE AS day,
        COUNT(DISTINCT application_id)::BIGINT AS n_terminated
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
      AND action IN (
          'MASTER_DATA_SUBMITTED',
          'APPLICATION_REJECTED',
          'APPLICATION_CANCELLED',
          'OFFER_REFUSED'
      )
    GROUP BY 1
)
SELECT
    day,
    n_terminated,
    AVG(n_terminated) OVER (
        ORDER BY day
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )::DOUBLE AS n_terminated_ma7
FROM daily
ORDER BY day;


-- Terminal completions: trailing 30 days ending at max(timestamp), vs average count
-- in each of the three prior non-overlapping 30-day blocks (older → newer).

WITH ref AS (
    SELECT max(timestamp)::DATE AS ref_d
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
),
bounds AS (
    SELECT
        ref_d,
        ref_d - INTERVAL '29 DAY' AS block0_start,
        ref_d AS block0_end,
        ref_d - INTERVAL '59 DAY' AS block1_start,
        ref_d - INTERVAL '30 DAY' AS block1_end,
        ref_d - INTERVAL '89 DAY' AS block2_start,
        ref_d - INTERVAL '60 DAY' AS block2_end,
        ref_d - INTERVAL '119 DAY' AS block3_start,
        ref_d - INTERVAL '90 DAY' AS block3_end
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
counts AS (
    SELECT
        (
            SELECT COUNT(DISTINCT application_id)
            FROM terminal
            CROSS JOIN bounds AS b
            WHERE d BETWEEN b.block0_start AND b.block0_end
        )::DOUBLE AS n_last_30d,
        (
            SELECT COUNT(DISTINCT application_id)
            FROM terminal
            CROSS JOIN bounds AS b
            WHERE d BETWEEN b.block1_start AND b.block1_end
        )::DOUBLE AS n_prev_a,
        (
            SELECT COUNT(DISTINCT application_id)
            FROM terminal
            CROSS JOIN bounds AS b
            WHERE d BETWEEN b.block2_start AND b.block2_end
        )::DOUBLE AS n_prev_b,
        (
            SELECT COUNT(DISTINCT application_id)
            FROM terminal
            CROSS JOIN bounds AS b
            WHERE d BETWEEN b.block3_start AND b.block3_end
        )::DOUBLE AS n_prev_c
)
SELECT
    n_last_30d::BIGINT AS n_completed_last_30d,
    ((n_prev_a + n_prev_b + n_prev_c) / 3.0) AS avg_completed_prior_3x30d,
    CASE
        WHEN (n_prev_a + n_prev_b + n_prev_c) > 0 THEN
            (
                (n_last_30d - ((n_prev_a + n_prev_b + n_prev_c) / 3.0))
                / ((n_prev_a + n_prev_b + n_prev_c) / 3.0)
            ) * 100.0
        ELSE NULL
    END AS pct_vs_prior_3_periods_trend
FROM counts;

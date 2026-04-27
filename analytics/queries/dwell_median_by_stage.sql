-- Median dwell (hours) per stage_order for completed stage segments, across all apps in the product filter.
-- Used in App investigator as a light cohort reference for one application.

WITH apps AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
)
SELECT
    d.stage_order,
    COUNT(*)::BIGINT AS n_segments,
    MEDIAN(d.dwell_hours)::DOUBLE AS median_dwell_hours
FROM v_stage_dwell AS d
INNER JOIN apps AS a ON a.application_id = d.application_id
WHERE d.dwell_hours IS NOT NULL
  AND d.dwell_hours > 0
GROUP BY d.stage_order
ORDER BY d.stage_order;

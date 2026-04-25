-- Period movers (unique applications with ≥1 logical stage change in-window).
-- Uses the same cohort definition as other period blocks (PHASE_0 §2).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
)
SELECT
    COUNT(DISTINCT t.application_id)::BIGINT AS n_movers
FROM v_transitions AS t
INNER JOIN cohort AS c ON c.application_id = t.application_id
WHERE t.transition_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}};

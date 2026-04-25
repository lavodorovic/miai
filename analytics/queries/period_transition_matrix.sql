-- Transition matrix (PHASE_0 §3): counts of logical stage changes in-period (transition_at::DATE
-- inclusive BETWEEN start/end). Cohort = same as other period queries (activity in window + product).
-- Unit: per transition (one row in v_transitions = one counted move); not per application.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
)
SELECT
    t.from_stage,
    t.to_stage,
    COUNT(*)::BIGINT AS n_transitions
FROM v_transitions AS t
INNER JOIN cohort AS c ON c.application_id = t.application_id
WHERE t.transition_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
GROUP BY t.from_stage, t.to_stage
ORDER BY t.from_stage, t.to_stage;

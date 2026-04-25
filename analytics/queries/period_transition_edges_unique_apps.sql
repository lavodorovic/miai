-- Period transition edges (unique apps per edge).
-- Cohort = apps with ≥1 audit row in the filter window + product (PHASE_0 §2).
-- During window: transition_at::DATE inclusive BETWEEN start/end.
-- Unit: distinct applications that experienced the edge at least once in-window.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
)
SELECT
    t.from_stage,
    t.to_stage,
    COUNT(DISTINCT t.application_id)::BIGINT AS n_apps
FROM v_transitions AS t
INNER JOIN cohort AS c ON c.application_id = t.application_id
WHERE t.transition_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
GROUP BY t.from_stage, t.to_stage
ORDER BY n_apps DESC, t.from_stage, t.to_stage;

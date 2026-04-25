-- Phase 1 validation: latest stage_order from v_audit_staged must match last transition to_stage
-- when any transition exists; single-row apps (no transitions) compare to themselves (always OK).
-- Returns one row: drift_rows (must be 0).

WITH latest_audit AS (
    SELECT
        application_id,
        stage_order AS st
    FROM v_audit_staged
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY application_id
        ORDER BY timestamp DESC, action DESC
    ) = 1
),
transition_latest AS (
    SELECT
        application_id,
        to_stage
    FROM v_transitions
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY application_id
        ORDER BY transition_at DESC, reason DESC
    ) = 1
)
SELECT
    COUNT(*)::BIGINT AS drift_rows
FROM latest_audit AS la
LEFT JOIN transition_latest AS tl USING (application_id)
WHERE la.st IS DISTINCT FROM COALESCE(tl.to_stage, la.st);

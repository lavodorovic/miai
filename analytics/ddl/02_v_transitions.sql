-- §3 transition facts: one row per logical stage change (dedup: consecutive rows with same stage_order omitted).
-- Columns: application_id, from_stage, to_stage, at, reason (audit action that landed in to_stage).
--
-- Gaps:
--   - No row for the first audit event per application (nothing to transition "from").
--   - from_stage / to_stage are INTEGER stage_order (same unit as funnel step_order), not labels.
--   - Multiple audit rows in one timestamp: ordered by action; still at most one transition per (prev,next) pair.

CREATE OR REPLACE VIEW v_transitions AS
WITH ordered AS (
    SELECT
        application_id,
        timestamp,
        action,
        stage_order,
        LAG(stage_order) OVER (
            PARTITION BY application_id
            ORDER BY timestamp, action
        ) AS from_stage
    FROM v_audit_staged
)
SELECT
    application_id,
    from_stage,
    stage_order AS to_stage,
    timestamp AS transition_at,
    action AS reason
FROM ordered
WHERE from_stage IS NOT NULL
  AND stage_order IS DISTINCT FROM from_stage;

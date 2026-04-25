-- Stage dwell facts derived from v_audit_staged.
-- One row per contiguous run in the same stage_order for an application.
--
-- Columns:
--   - entered_at: timestamp of the first audit row in the run
--   - exited_at: timestamp of the next stage entry (NULL if still open)
--   - dwell_hours: hours between entered_at and exited_at (NULL if open)
--   - is_open: exited_at IS NULL

CREATE OR REPLACE VIEW v_stage_dwell AS
WITH ordered AS (
    SELECT
        application_id,
        product_type,
        timestamp,
        action,
        actor,
        stage_order,
        LAG(stage_order) OVER (
            PARTITION BY application_id
            ORDER BY timestamp, action
        ) AS prev_stage
    FROM v_audit_staged
),
stage_entries AS (
    SELECT
        application_id,
        product_type,
        stage_order,
        timestamp AS entered_at,
        actor AS current_actor,
        action AS current_action,
        ROW_NUMBER() OVER (
            PARTITION BY application_id
            ORDER BY timestamp, action
        ) AS rn
    FROM ordered
    WHERE prev_stage IS NULL OR stage_order IS DISTINCT FROM prev_stage
),
with_exit AS (
    SELECT
        application_id,
        product_type,
        stage_order,
        entered_at,
        LEAD(entered_at) OVER (
            PARTITION BY application_id
            ORDER BY entered_at
        ) AS exited_at,
        current_actor,
        current_action
    FROM stage_entries
)
SELECT
    application_id,
    product_type,
    stage_order,
    entered_at,
    exited_at,
    CASE
        WHEN exited_at IS NULL THEN NULL
        ELSE EXTRACT(EPOCH FROM (exited_at - entered_at)) / 3600.0
    END AS dwell_hours,
    (exited_at IS NULL) AS is_open,
    current_actor,
    current_action
FROM with_exit;


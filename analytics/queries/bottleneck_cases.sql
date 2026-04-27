WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.stage_order,
        a.action,
        a.timestamp AS latest_at,
        a.actor AS latest_actor
    FROM v_audit_staged AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER_A}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
open_dwell AS (
    SELECT
        application_id,
        stage_order,
        entered_at,
        (EXTRACT(EPOCH FROM (current_timestamp - entered_at)) / 86400.0) AS days_in_stage
    FROM v_stage_dwell
    WHERE is_open
)
SELECT
    l.application_id,
    l.stage_order,
    l.action AS current_action,
    l.latest_actor,
    l.latest_at,
    COALESCE(d.days_in_stage, 0.0) AS days_in_stage
FROM latest AS l
LEFT JOIN open_dwell AS d
  ON d.application_id = l.application_id
 AND d.stage_order = l.stage_order
WHERE l.action NOT IN (
    'MASTER_DATA_SUBMITTED',
    'APPLICATION_REJECTED',
    'APPLICATION_CANCELLED',
    'OFFER_REFUSED'
)
ORDER BY days_in_stage DESC, latest_at ASC
LIMIT 50;

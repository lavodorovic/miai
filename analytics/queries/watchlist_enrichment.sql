WITH latest AS (
    SELECT
        a.application_id,
        arg_max(t.team, a.timestamp) AS team,
        arg_max(a.timestamp, a.timestamp) AS last_ts
    FROM audit_logs AS a
    LEFT JOIN v_team AS t
      ON t.application_id = a.application_id
     AND t.timestamp = a.timestamp
     AND t.action = a.action
     AND t.actor = a.actor
    WHERE {{PRODUCT_TYPE_FILTER_A}}
    GROUP BY a.application_id
),
cur AS (
    SELECT
        d.application_id,
        d.entered_at,
        d.is_open
    FROM v_stage_dwell AS d
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY d.application_id
        ORDER BY d.entered_at DESC
    ) = 1
)
SELECT
    l.application_id,
    COALESCE(l.team, 'Other') AS waiting_on,
    (EXTRACT(EPOCH FROM (current_timestamp - c.entered_at)) / 86400.0) AS days_in_current_stage
FROM latest AS l
LEFT JOIN cur AS c USING (application_id);

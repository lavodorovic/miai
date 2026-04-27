WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.actor,
        COALESCE(t.team, 'Other') AS team,
        a.action,
        a.timestamp AS latest_at
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    LEFT JOIN v_team AS t
      ON t.application_id = a.application_id
     AND t.timestamp = a.timestamp
     AND t.action = a.action
     AND t.actor = a.actor
    WHERE {{PRODUCT_TYPE_FILTER_A}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
cur AS (
    SELECT
        application_id,
        (EXTRACT(EPOCH FROM (current_timestamp - entered_at)) / 86400.0) AS days_in_stage
    FROM v_stage_dwell
    WHERE is_open
)
SELECT
    l.application_id,
    l.team,
    l.actor,
    l.action AS current_action,
    l.latest_at,
    COALESCE(c.days_in_stage, 0.0) AS days_in_stage
FROM latest AS l
LEFT JOIN cur AS c USING (application_id)
WHERE l.team IN ('CR', 'Compliance')
  AND l.action NOT IN (
      'MASTER_DATA_SUBMITTED',
      'APPLICATION_REJECTED',
      'APPLICATION_CANCELLED',
      'OFFER_REFUSED'
  )
ORDER BY days_in_stage DESC, latest_at ASC
LIMIT 50;

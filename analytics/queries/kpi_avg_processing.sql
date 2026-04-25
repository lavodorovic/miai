WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
started AS (
    SELECT
        a.application_id,
        MIN(a.timestamp) AS started_at
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND a.action = 'APPLICATION_STARTED'
    GROUP BY a.application_id
),
last_ts AS (
    SELECT
        a.application_id,
        MAX(a.timestamp) AS last_at
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY a.application_id
)
SELECT
    AVG(date_diff('day', s.started_at, l.last_at))::DOUBLE AS avg_days
FROM started AS s
INNER JOIN last_ts AS l USING (application_id)
WHERE s.started_at IS NOT NULL;

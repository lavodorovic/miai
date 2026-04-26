-- Count of in-flight applications (last event not terminal) where latest activity is more than 24h ago.
-- Same spirit as stuck_applications (48h) with a 24h threshold for a lighter "stale" signal on overview.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
last_evt AS (
    SELECT
        application_id,
        MAX(timestamp) AS latest_at
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND application_id IN (SELECT application_id FROM cohort)
    GROUP BY application_id
),
last_row AS (
    SELECT
        f.application_id,
        f.action,
        f.latest_at
    FROM (
        SELECT
            l.application_id,
            l.latest_at,
            a.action,
            ROW_NUMBER() OVER (
                PARTITION BY l.application_id
                ORDER BY a.timestamp DESC, a.action DESC
            ) AS rn
        FROM last_evt AS l
        INNER JOIN audit_logs AS a
            ON a.application_id = l.application_id
            AND a.timestamp = l.latest_at
        WHERE {{PRODUCT_TYPE_FILTER}}
    ) AS f
    WHERE f.rn = 1
)
SELECT
    COUNT(*)::BIGINT AS n_stale_24h
FROM last_row
WHERE latest_at < (current_timestamp - INTERVAL 24 HOUR)
  AND action NOT IN (
        'MASTER_DATA_SUBMITTED',
        'APPLICATION_REJECTED',
        'APPLICATION_CANCELLED',
        'OFFER_REFUSED'
    );

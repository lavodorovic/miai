WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.action AS current_action
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
)
SELECT COUNT(*)::BIGINT AS n
FROM latest
WHERE current_action NOT IN (
    'MASTER_DATA_SUBMITTED',
    'APPLICATION_REJECTED',
    'APPLICATION_CANCELLED',
    'OFFER_REFUSED'
);

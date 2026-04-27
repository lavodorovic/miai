-- Share of cohort apps that had OFFER_SENT at least once, by interaction-loop bucket.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
per_app AS (
    SELECT
        a.application_id,
        SUM(
            CASE WHEN a.action = 'INTERACTION_STARTED' THEN 1 ELSE 0 END
        )::BIGINT AS n_interactions
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON c.application_id = a.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY 1
),
bucketed AS (
    SELECT
        application_id,
        CASE
            WHEN n_interactions = 0 THEN '0'
            WHEN n_interactions = 1 THEN '1'
            WHEN n_interactions = 2 THEN '2'
            WHEN n_interactions IN (3, 4) THEN '3-4'
            ELSE '5+'
        END AS interaction_bucket
    FROM per_app
),
offers AS (
    SELECT DISTINCT a.application_id
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON c.application_id = a.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND a.action = 'OFFER_SENT'
)
SELECT
    b.interaction_bucket,
    COUNT(*)::BIGINT AS n_apps,
    SUM(
        CASE
            WHEN o.application_id IS NOT NULL THEN 1
            ELSE 0
        END
    )::BIGINT AS n_reached_offer
FROM bucketed AS b
LEFT JOIN offers AS o ON o.application_id = b.application_id
GROUP BY b.interaction_bucket
ORDER BY
    CASE b.interaction_bucket
        WHEN '0' THEN 1
        WHEN '1' THEN 2
        WHEN '2' THEN 3
        WHEN '3-4' THEN 4
        WHEN '5+' THEN 5
        ELSE 9
    END;

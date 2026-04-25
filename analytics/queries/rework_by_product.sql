-- Rework overview broken down by product_type.
-- Cohort = apps with any activity in selected product + date window.

WITH cohort AS (
    SELECT DISTINCT application_id, product_type
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
per_app AS (
    SELECT
        c.product_type,
        a.application_id,
        SUM(CASE WHEN a.action = 'INTERACTION_STARTED' THEN 1 ELSE 0 END) AS n_interactions,
        SUM(CASE WHEN a.action = 'ANSWERS_EDIT_STARTED' THEN 1 ELSE 0 END) AS n_answers_edit,
        MIN(CASE WHEN a.action = 'LABEL_ADDED' THEN a.timestamp ELSE NULL END) AS first_label_at,
        MAX(CASE WHEN a.action = 'COMPLIANCE_REVIEW_STARTED' THEN a.timestamp ELSE NULL END) AS last_compliance_start_at
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY c.product_type, a.application_id
)
SELECT
    product_type,
    COUNT(*)::BIGINT AS n_apps_total,
    SUM(CASE WHEN n_interactions >= 1 THEN 1 ELSE 0 END)::BIGINT AS n_apps_with_interactions,
    SUM(CASE WHEN n_interactions >= 2 THEN 1 ELSE 0 END)::BIGINT AS n_apps_2plus_interactions,
    SUM(CASE WHEN n_interactions >= 3 THEN 1 ELSE 0 END)::BIGINT AS n_apps_3plus_interactions,
    SUM(CASE WHEN n_answers_edit >= 1 THEN 1 ELSE 0 END)::BIGINT AS n_apps_with_answers_edit,
    SUM(
        CASE
            WHEN first_label_at IS NOT NULL
             AND last_compliance_start_at IS NOT NULL
             AND last_compliance_start_at > first_label_at
            THEN 1 ELSE 0
        END
    )::BIGINT AS n_apps_with_compliance_reopened,
    (100.0 * SUM(CASE WHEN n_interactions <= 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0))::DOUBLE AS pct_first_pass
FROM per_app
GROUP BY product_type
ORDER BY n_apps_total DESC, product_type;


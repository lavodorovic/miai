WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
per_app AS (
    SELECT
        a.application_id,
        SUM(CASE WHEN a.action = 'INTERACTION_STARTED' THEN 1 ELSE 0 END) AS n_interactions,
        SUM(CASE WHEN a.action = 'ANSWERS_EDIT_STARTED' THEN 1 ELSE 0 END) AS n_answers_edit,
        MIN(CASE WHEN a.action = 'LABEL_ADDED' THEN a.timestamp ELSE NULL END) AS first_label_at,
        MAX(CASE WHEN a.action = 'COMPLIANCE_REVIEW_STARTED' THEN a.timestamp ELSE NULL END) AS last_compliance_start_at,
        MAX(a.timestamp) AS latest_at,
        arg_max(a.actor, a.timestamp) AS latest_actor,
        arg_max(a.action, a.timestamp) AS latest_action
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    GROUP BY a.application_id
)
SELECT
    application_id,
    n_interactions,
    n_answers_edit,
    CASE
        WHEN first_label_at IS NOT NULL
         AND last_compliance_start_at IS NOT NULL
         AND last_compliance_start_at > first_label_at
        THEN TRUE ELSE FALSE
    END AS compliance_reopened,
    latest_at,
    latest_actor,
    latest_action
FROM per_app
WHERE n_interactions >= 2
   OR n_answers_edit >= 1
   OR (
        first_label_at IS NOT NULL
    AND last_compliance_start_at IS NOT NULL
    AND last_compliance_start_at > first_label_at
   )
ORDER BY n_interactions DESC, compliance_reopened DESC, latest_at DESC
LIMIT 25;

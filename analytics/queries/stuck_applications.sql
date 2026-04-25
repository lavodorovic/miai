-- In-flight apps: true latest event (full history) is >48h old and not a terminal outcome.
-- Cohort = apps with any activity in the selected product + date window.
--
-- case_owner = Relio ops on file (APP_ASSIGNED, else ACCOUNT_MANAGER_ASSIGNED) — who owns the case
--   when the ball is on the customer (e.g. INTERACTION_SUBMITTED), latest_actor is often the customer;
--   case_owner is still the internal owner for follow-up.

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
        f.actor AS latest_actor,
        f.action,
        f.latest_at
    FROM (
        SELECT
            l.application_id,
            l.latest_at,
            a.actor,
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
),
app_owner AS (
    SELECT
        a.application_id,
        arg_max(a.actor, a.timestamp) AS case_owner
    FROM audit_logs AS a
    WHERE a.action = 'APP_ASSIGNED'
      AND {{PRODUCT_TYPE_FILTER}}
    GROUP BY a.application_id
),
mgr_owner AS (
    SELECT
        a.application_id,
        arg_max(a.actor, a.timestamp) AS case_owner
    FROM audit_logs AS a
    WHERE a.action = 'ACCOUNT_MANAGER_ASSIGNED'
      AND {{PRODUCT_TYPE_FILTER}}
    GROUP BY a.application_id
)
SELECT
    lr.application_id,
    COALESCE(ao.case_owner, mo.case_owner, '(not assigned)') AS case_owner,
    lr.latest_actor,
    lr.action AS current_action,
    lr.latest_at
FROM last_row AS lr
LEFT JOIN app_owner AS ao ON lr.application_id = ao.application_id
LEFT JOIN mgr_owner AS mo ON lr.application_id = mo.application_id
WHERE lr.latest_at < (current_timestamp - INTERVAL 48 HOUR)
  AND lr.action NOT IN (
      'MASTER_DATA_SUBMITTED',
      'APPLICATION_REJECTED',
      'APPLICATION_CANCELLED',
      'OFFER_REFUSED'
  )
ORDER BY lr.latest_at ASC;

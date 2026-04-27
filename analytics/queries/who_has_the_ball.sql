-- Who has the ball: team of the latest audit event for in-flight applications.
-- Cohort = apps with any activity in selected product + date window.
-- In-flight = latest action is not terminal.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.action,
        t.team
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
inflight AS (
    SELECT
        application_id,
        COALESCE(team, 'Other') AS team
    FROM latest
    WHERE action NOT IN (
        'MASTER_DATA_SUBMITTED',
        'APPLICATION_REJECTED',
        'APPLICATION_CANCELLED',
        'OFFER_REFUSED'
    )
),
agg AS (
    SELECT team, COUNT(*)::BIGINT AS n_applications
    FROM inflight
    GROUP BY team
),
tot AS (
    SELECT SUM(n_applications)::DOUBLE AS total FROM agg
)
SELECT
    a.team,
    a.n_applications,
    CASE WHEN t.total IS NULL OR t.total = 0 THEN 0.0 ELSE (100.0 * a.n_applications / t.total) END AS pct_of_inflight
FROM agg AS a
CROSS JOIN tot AS t
ORDER BY a.n_applications DESC, a.team;


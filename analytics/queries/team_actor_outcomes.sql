-- Terminal outcome mix by actor/team in the 30d completion window (aligned with team_workload end date).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
window_bounds AS (
    SELECT
        ({{PERIOD_END_DATE}} - INTERVAL 29 DAY) AS d30_start,
        {{PERIOD_END_DATE}} AS d_end
),
terminal_rows AS (
    SELECT
        a.application_id,
        a.actor,
        COALESCE(t.team, 'Other') AS team,
        a.action
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON c.application_id = a.application_id
    LEFT JOIN v_team AS t
        ON t.application_id = a.application_id
        AND t.timestamp = a.timestamp
        AND t.action = a.action
        AND t.actor = a.actor
    CROSS JOIN window_bounds AS w
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND a.timestamp::DATE BETWEEN w.d30_start AND w.d_end
      AND a.action IN (
          'MASTER_DATA_SUBMITTED',
          'APPLICATION_REJECTED',
          'APPLICATION_CANCELLED',
          'OFFER_REFUSED'
      )
      AND COALESCE(t.team, 'Other') IN ('CR', 'Compliance')
)
SELECT
    actor,
    team,
    COUNT(DISTINCT CASE WHEN action = 'MASTER_DATA_SUBMITTED' THEN application_id END)::BIGINT AS n_approved,
    COUNT(DISTINCT CASE WHEN action = 'APPLICATION_REJECTED' THEN application_id END)::BIGINT AS n_rejected,
    COUNT(
        DISTINCT CASE
            WHEN action IN ('APPLICATION_CANCELLED', 'OFFER_REFUSED') THEN application_id
        END
    )::BIGINT AS n_other_terminal
FROM terminal_rows
GROUP BY 1, 2
HAVING
    n_approved + n_rejected + n_other_terminal > 0
ORDER BY team, n_approved + n_rejected + n_other_terminal DESC, actor;

-- Terminal completions per calendar day, actor, and team (CR / Compliance) for cohort + period.
-- For heatmaps of "who closed what, when" on Team workload; independent of the capacity mock calendars.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
terminal_rows AS (
    SELECT
        a.application_id,
        a.actor,
        a.timestamp::DATE AS day,
        COALESCE(t.team, 'Other') AS team
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON c.application_id = a.application_id
    LEFT JOIN v_team AS t
        ON t.application_id = a.application_id
        AND t.timestamp = a.timestamp
        AND t.action = a.action
        AND t.actor = a.actor
    WHERE {{PRODUCT_TYPE_FILTER_A}}
      AND a.timestamp::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
      AND a.action IN (
          'MASTER_DATA_SUBMITTED',
          'APPLICATION_REJECTED',
          'APPLICATION_CANCELLED',
          'OFFER_REFUSED'
      )
)
SELECT
    day,
    actor,
    team,
    COUNT(DISTINCT application_id)::BIGINT AS n_completions
FROM terminal_rows
WHERE team IN ('CR', 'Compliance')
GROUP BY 1, 2, 3
ORDER BY day, team, n_completions DESC, actor;

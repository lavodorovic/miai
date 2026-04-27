-- Team workload (per actor) for CR + Compliance.
-- Open cases now = apps whose latest actor is the given actor AND app is in-flight.
-- Completed_7d/30d = terminal outcomes in the last 7/30 calendar days of the selected window.

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.actor,
        a.action,
        a.timestamp
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
latest_team AS (
    SELECT
        l.application_id,
        l.actor,
        COALESCE(t.team, 'Other') AS team,
        l.action,
        l.timestamp AS latest_at
    FROM latest AS l
    LEFT JOIN v_team AS t
      ON t.application_id = l.application_id
     AND t.timestamp = l.timestamp
     AND t.action = l.action
     AND t.actor = l.actor
),
inflight_latest AS (
    SELECT *
    FROM latest_team
    WHERE action NOT IN (
        'MASTER_DATA_SUBMITTED',
        'APPLICATION_REJECTED',
        'APPLICATION_CANCELLED',
        'OFFER_REFUSED'
    )
      AND team IN ('CR', 'Compliance')
),
open_cases AS (
    SELECT
        actor,
        team,
        COUNT(DISTINCT application_id)::BIGINT AS open_cases_now,
        QUANTILE_CONT(EXTRACT(EPOCH FROM (current_timestamp - latest_at)) / 86400.0, 0.90) AS p90_age_open_days
    FROM inflight_latest
    GROUP BY actor, team
),
window_bounds AS (
    SELECT
        ({{PERIOD_END_DATE}} - INTERVAL 6 DAY) AS d7_start,
        ({{PERIOD_END_DATE}} - INTERVAL 29 DAY) AS d30_start,
        {{PERIOD_END_DATE}} AS d_end
),
terminal_events AS (
    SELECT
        a.actor,
        COALESCE(t.team, 'Other') AS team,
        a.application_id,
        a.timestamp::DATE AS day
    FROM audit_logs AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    LEFT JOIN v_team AS t
      ON t.application_id = a.application_id
     AND t.timestamp = a.timestamp
     AND t.action = a.action
     AND t.actor = a.actor
    CROSS JOIN window_bounds AS w
    WHERE {{PRODUCT_TYPE_FILTER_A}}
      AND a.action IN (
          'MASTER_DATA_SUBMITTED',
          'APPLICATION_REJECTED',
          'APPLICATION_CANCELLED',
          'OFFER_REFUSED'
      )
      AND a.timestamp::DATE BETWEEN w.d30_start AND w.d_end
      AND COALESCE(t.team, 'Other') IN ('CR', 'Compliance')
),
completed AS (
    SELECT
        actor,
        team,
        COUNT(DISTINCT CASE WHEN day >= (SELECT d7_start FROM window_bounds) THEN application_id END)::BIGINT AS completed_7d,
        COUNT(DISTINCT application_id)::BIGINT AS completed_30d
    FROM terminal_events
    GROUP BY actor, team
),
actor_minutes AS (
    -- Proxy effort: median minutes between consecutive actions by actor on same app (last 30d window).
    WITH ordered AS (
        SELECT
            a.actor,
            COALESCE(t.team, 'Other') AS team,
            a.application_id,
            a.timestamp,
            LEAD(a.timestamp) OVER (
                PARTITION BY a.actor, a.application_id
                ORDER BY a.timestamp, a.action
            ) AS next_ts
        FROM audit_logs AS a
        INNER JOIN cohort AS c ON a.application_id = c.application_id
        LEFT JOIN v_team AS t
          ON t.application_id = a.application_id
         AND t.timestamp = a.timestamp
         AND t.action = a.action
         AND t.actor = a.actor
        CROSS JOIN window_bounds AS w
        WHERE {{PRODUCT_TYPE_FILTER_A}}
          AND a.timestamp::DATE BETWEEN w.d30_start AND w.d_end
          AND COALESCE(t.team, 'Other') IN ('CR', 'Compliance')
    )
    SELECT
        actor,
        team,
        MEDIAN(EXTRACT(EPOCH FROM (next_ts - timestamp)) / 60.0) AS med_minutes_between_actions_30d
    FROM ordered
    WHERE next_ts IS NOT NULL
    GROUP BY actor, team
),
team_median_open AS (
    SELECT
        team,
        MEDIAN(open_cases_now) AS team_median_open
    FROM open_cases
    GROUP BY team
)
SELECT
    COALESCE(o.actor, c.actor, m.actor) AS actor,
    COALESCE(o.team, c.team, m.team) AS team,
    COALESCE(o.open_cases_now, 0)::BIGINT AS open_cases_now,
    COALESCE(c.completed_7d, 0)::BIGINT AS completed_7d,
    COALESCE(c.completed_30d, 0)::BIGINT AS completed_30d,
    COALESCE(m.med_minutes_between_actions_30d, 0.0) AS med_minutes_between_actions_30d,
    COALESCE(o.p90_age_open_days, 0.0) AS p90_age_open_days,
    CASE
        WHEN t.team_median_open IS NULL THEN FALSE
        ELSE (COALESCE(o.open_cases_now, 0) > (1.5 * t.team_median_open))
    END AS suggested_rebalance_flag
FROM open_cases AS o
FULL OUTER JOIN completed AS c USING (actor, team)
FULL OUTER JOIN actor_minutes AS m USING (actor, team)
LEFT JOIN team_median_open AS t ON COALESCE(o.team, c.team, m.team) = t.team
ORDER BY team, open_cases_now DESC, completed_7d DESC, actor;


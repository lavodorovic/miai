-- Swimlane funnel (collapsed view of the 34-stage funnel).
-- Cohort = apps with any row in selected product + date window.
-- Current stage = true latest audit row per app (full history).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.stage_order AS step_order,
        a.timestamp AS last_event_at
    FROM v_audit_staged AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
swimlaned AS (
    SELECT
        application_id,
        last_event_at,
        CASE
            WHEN step_order IN (1, 2, 3) THEN 1
            WHEN step_order IN (4, 5) THEN 2
            WHEN step_order IN (6, 7) THEN 3
            WHEN step_order IN (8, 15, 16) THEN 4
            WHEN step_order IN (9, 10, 11, 12, 13, 14) THEN 5
            WHEN step_order IN (19, 20, 21, 23, 24, 25) THEN 6
            WHEN step_order IN (17, 18, 22, 26) THEN 7
            ELSE 8
        END AS swimlane_order
    FROM latest
),
swimlane_dim AS (
    SELECT * FROM (VALUES
        (1, 'Intake'),
        (2, 'Assignment'),
        (3, 'CR review'),
        (4, 'Compliance'),
        (5, 'Interaction / RFI'),
        (6, 'Offer & onboarding'),
        (7, 'Terminal'),
        (8, 'Other / unknown')
    ) AS t(swimlane_order, swimlane_label)
),
agg AS (
    SELECT
        swimlane_order,
        COUNT(DISTINCT application_id)::BIGINT AS active_applications,
        AVG(date_diff('day', last_event_at, current_timestamp)::DOUBLE) AS avg_days_in_stage
    FROM swimlaned
    GROUP BY swimlane_order
)
SELECT
    d.swimlane_order,
    d.swimlane_label,
    COALESCE(a.active_applications, 0)::BIGINT AS active_applications,
    COALESCE(a.avg_days_in_stage, 0.0) AS avg_days_in_stage
FROM swimlane_dim AS d
LEFT JOIN agg AS a USING (swimlane_order)
ORDER BY d.swimlane_order;


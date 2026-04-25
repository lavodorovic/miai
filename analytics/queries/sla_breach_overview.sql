-- SLA breach overview for in-flight applications (as-of now).
--
-- Thresholds (v0):
--   - CR review:       24h
--   - Compliance:      48h
--   - Interaction/RFI: 72h (waiting on customer when last action is INTERACTION_STARTED)
--   - Offer/onboarding: 5d

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.stage_order,
        a.action,
        a.timestamp AS last_event_at
    FROM v_audit_staged AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
inflight AS (
    SELECT
        application_id,
        stage_order,
        action,
        last_event_at,
        (EXTRACT(EPOCH FROM (current_timestamp - last_event_at)) / 3600.0) AS hours_since_last_event
    FROM latest
    WHERE action NOT IN (
        'MASTER_DATA_SUBMITTED',
        'APPLICATION_REJECTED',
        'APPLICATION_CANCELLED',
        'OFFER_REFUSED'
    )
),
bucketed AS (
    SELECT
        application_id,
        hours_since_last_event,
        CASE
            WHEN stage_order IN (6, 7) THEN 'CR review'
            WHEN stage_order IN (8, 15, 16) THEN 'Compliance'
            WHEN stage_order IN (9, 10, 11, 12, 13, 14) THEN 'Interaction / RFI'
            WHEN stage_order IN (19, 20, 21, 23, 24, 25) THEN 'Offer & onboarding'
            ELSE 'Other'
        END AS sla_area,
        CASE
            WHEN stage_order IN (6, 7) THEN 24.0
            WHEN stage_order IN (8, 15, 16) THEN 48.0
            WHEN stage_order IN (9, 10, 11, 12, 13, 14) THEN 72.0
            WHEN stage_order IN (19, 20, 21, 23, 24, 25) THEN 120.0
            ELSE 48.0
        END AS sla_hours,
        action
    FROM inflight
),
scored AS (
    SELECT
        sla_area,
        CASE
            WHEN hours_since_last_event >= sla_hours THEN 'breached'
            WHEN hours_since_last_event >= (0.8 * sla_hours) THEN 'at_risk'
            ELSE 'ok'
        END AS status,
        COUNT(*)::BIGINT AS n_applications
    FROM bucketed
    WHERE NOT (sla_area = 'Interaction / RFI' AND action <> 'INTERACTION_STARTED')
    GROUP BY 1, 2
)
SELECT
    sla_area,
    status,
    n_applications
FROM scored
ORDER BY
    CASE sla_area
        WHEN 'CR review' THEN 1
        WHEN 'Compliance' THEN 2
        WHEN 'Interaction / RFI' THEN 3
        WHEN 'Offer & onboarding' THEN 4
        ELSE 99
    END,
    CASE status WHEN 'breached' THEN 1 WHEN 'at_risk' THEN 2 ELSE 3 END;


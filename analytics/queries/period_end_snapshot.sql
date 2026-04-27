-- End-of-period snapshot (PHASE_0 §2): same cohort as period_start_snapshot.
-- Latest mapped stage using rows with timestamp::DATE <= period end (inclusive, naive).
-- Every cohort app has ≥1 row in-window, so step_order 0 is unused here (kept for symmetric join UX).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
asof_end AS (
    SELECT
        a.application_id,
        a.stage_order AS step_order,
        a.timestamp AS last_event_at
    FROM v_audit_staged AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER_A}}
      AND a.timestamp::DATE <= {{PERIOD_END_DATE}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
agg AS (
    SELECT
        step_order,
        COUNT(*)::BIGINT AS active_applications,
        AVG(date_diff('day', last_event_at, current_timestamp)::DOUBLE) AS avg_days_in_stage
    FROM asof_end
    GROUP BY step_order
),
funnel_dim AS (
    SELECT * FROM (VALUES
        (0, '00 · (no audit before period start)'),
        (1, '01 · INITIAL (application started)'),
        (2, '02 · SUBMITTED (application submitted)'),
        (3, '03 · DOCUMENTS_UPLOAD (docs submitted)'),
        (4, '04 · Ops queue · account manager assigned'),
        (5, '05 · Ops queue · app assigned'),
        (6, '06 · REVIEW · CR review started'),
        (7, '07 · REVIEW · CR review completed'),
        (8, '08 · REVIEW · compliance review started'),
        (9, '09 · INTERACTION_SUMMARY (RFI sent)'),
        (10, '10 · INTERACTION_SUBMITTED'),
        (11, '11 · INTERACTION_CANCELLED (CR interaction cancelled)'),
        (12, '12 · CR interaction started'),
        (13, '13 · INTERACTION_EDIT · answers edit started'),
        (14, '14 · INTERACTION_EDIT · answers edit finished'),
        (15, '15 · REVIEW · label added'),
        (16, '16 · REVIEW · compliance review completed'),
        (17, '17 · REJECTED (application rejected)'),
        (18, '18 · CANCELLED (application cancelled)'),
        (19, '19 · APPROVED path · offer prepared'),
        (20, '20 · OFFER_SENT'),
        (21, '21 · OFFER_RESPONSE (acceptOffer)'),
        (22, '22 · OFFER_REFUSED'),
        (23, '23 · Post-accept · video ident sent'),
        (24, '24 · Post-accept · video ident finished'),
        (25, '25 · Post-accept · enrollment approved'),
        (26, '26 · Post-accept · master data submitted'),
        (27, '27 · OFFER_EXPIRED (reserved)'),
        (28, '28 · OFFER_ACCEPTED (reserved)'),
        (29, '29 · DOCUMENTS_UPLOAD state (reserved)'),
        (30, '30 · ON_HOLD (reserved)'),
        (31, '31 · APPROVED internal state (reserved)'),
        (32, '32 · IN_PROGRESS / SUMMARY (reserved)'),
        (33, '33 · EDIT_ANSWERS customer journey (reserved)'),
        (34, '34 · Other / unknown action')
    ) AS t(step_order, step_label)
)
SELECT
    d.step_order,
    d.step_label,
    COALESCE(a.active_applications, 0)::BIGINT AS active_applications,
    COALESCE(a.avg_days_in_stage, 0.0) AS avg_days_in_stage
FROM funnel_dim AS d
LEFT JOIN agg AS a USING (step_order)
ORDER BY d.step_order;

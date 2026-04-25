WITH cur AS (
    SELECT *
    FROM v_stage_dwell
    WHERE {{APP_ID_FILTER}}
      AND {{PRODUCT_TYPE_FILTER}}
    ORDER BY entered_at
),
dim AS (
    SELECT * FROM (VALUES
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
        (34, '34 · Other / unknown action')
    ) AS t(stage_order, stage_label)
)
SELECT
    c.entered_at,
    c.exited_at,
    c.stage_order,
    d.stage_label,
    COALESCE(c.dwell_hours, EXTRACT(EPOCH FROM (current_timestamp - c.entered_at)) / 3600.0) AS dwell_hours
FROM cur AS c
LEFT JOIN dim AS d ON c.stage_order = d.stage_order
ORDER BY c.entered_at;

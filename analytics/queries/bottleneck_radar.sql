-- Bottleneck radar per stage (34-step canonical stages).
-- Metrics are intended for ranking and triage, not for accounting.
--
-- Definitions:
--   - wip_now: distinct apps whose latest stage_order equals this stage (as-of now; cohort gated by window)
--   - inflow_7d/outflow_7d: transitions into/out of stage in the last 7 days of the selected window
--   - p50/p90 dwell hours: dwell for stage entries that exited during the selected window (from v_stage_dwell)
--   - aging buckets: age of open stage entries as-of now (days since entered_at)
--   - bottleneck_score: composite z-score of wip_now + 1.5*net_7d + p90_dwell_hours

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
latest AS (
    SELECT
        a.application_id,
        a.stage_order AS stage_order,
        a.action AS action
    FROM v_audit_staged AS a
    INNER JOIN cohort AS c ON a.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER_A}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp DESC, a.action DESC
    ) = 1
),
inflight AS (
    SELECT application_id, stage_order
    FROM latest
    WHERE action NOT IN (
        'MASTER_DATA_SUBMITTED',
        'APPLICATION_REJECTED',
        'APPLICATION_CANCELLED',
        'OFFER_REFUSED'
    )
),
wip AS (
    SELECT stage_order, COUNT(*)::BIGINT AS wip_now
    FROM inflight
    GROUP BY stage_order
),
last7 AS (
    SELECT
        ({{PERIOD_END_DATE}} - INTERVAL 6 DAY) AS d0,
        {{PERIOD_END_DATE}} AS d1
),
tr AS (
    SELECT
        t.from_stage,
        t.to_stage
    FROM v_transitions AS t
    INNER JOIN cohort AS c ON t.application_id = c.application_id
    CROSS JOIN last7 AS w
    WHERE t.transition_at::DATE BETWEEN w.d0 AND w.d1
),
flow AS (
    SELECT
        stage_order,
        SUM(inflow)::BIGINT AS inflow_7d,
        SUM(outflow)::BIGINT AS outflow_7d
    FROM (
        SELECT to_stage AS stage_order, COUNT(*) AS inflow, 0 AS outflow
        FROM tr
        GROUP BY to_stage
        UNION ALL
        SELECT from_stage AS stage_order, 0 AS inflow, COUNT(*) AS outflow
        FROM tr
        GROUP BY from_stage
    ) x
    GROUP BY stage_order
),
dwell AS (
    SELECT
        stage_order,
        MEDIAN(dwell_hours) AS p50_dwell_hours,
        QUANTILE_CONT(dwell_hours, 0.90) AS p90_dwell_hours
    FROM v_stage_dwell AS d
    INNER JOIN cohort AS c ON d.application_id = c.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND d.exited_at IS NOT NULL
      AND d.exited_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
      AND d.dwell_hours IS NOT NULL
    GROUP BY stage_order
),
aging AS (
    SELECT
        stage_order,
        SUM(CASE WHEN age_days < 1 THEN 1 ELSE 0 END)::BIGINT AS aging_0_24h,
        SUM(CASE WHEN age_days >= 1 AND age_days < 3 THEN 1 ELSE 0 END)::BIGINT AS aging_1_3d,
        SUM(CASE WHEN age_days >= 3 AND age_days < 7 THEN 1 ELSE 0 END)::BIGINT AS aging_3_7d,
        SUM(CASE WHEN age_days >= 7 THEN 1 ELSE 0 END)::BIGINT AS aging_7d_plus
    FROM (
        SELECT
            d.stage_order,
            (EXTRACT(EPOCH FROM (current_timestamp - d.entered_at)) / 86400.0) AS age_days
        FROM v_stage_dwell AS d
        INNER JOIN cohort AS c ON d.application_id = c.application_id
        WHERE {{PRODUCT_TYPE_FILTER}}
          AND d.is_open
    ) o
    GROUP BY stage_order
),
stage_dim AS (
    SELECT DISTINCT step_order AS stage_order, step_label
    FROM (
        SELECT step_order, step_label FROM (VALUES
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
        ) AS t(step_order, step_label)
    )
),
base AS (
    SELECT
        d.stage_order,
        d.step_label,
        COALESCE(w.wip_now, 0) AS wip_now,
        COALESCE(f.inflow_7d, 0) AS inflow_7d,
        COALESCE(f.outflow_7d, 0) AS outflow_7d,
        (COALESCE(f.inflow_7d, 0) - COALESCE(f.outflow_7d, 0)) AS net_7d,
        COALESCE(dw.p50_dwell_hours, 0.0) AS p50_dwell_hours,
        COALESCE(dw.p90_dwell_hours, 0.0) AS p90_dwell_hours,
        COALESCE(a.aging_0_24h, 0) AS aging_0_24h,
        COALESCE(a.aging_1_3d, 0) AS aging_1_3d,
        COALESCE(a.aging_3_7d, 0) AS aging_3_7d,
        COALESCE(a.aging_7d_plus, 0) AS aging_7d_plus
    FROM stage_dim AS d
    LEFT JOIN wip AS w USING (stage_order)
    LEFT JOIN flow AS f USING (stage_order)
    LEFT JOIN dwell AS dw USING (stage_order)
    LEFT JOIN aging AS a USING (stage_order)
),
zs AS (
    SELECT
        *,
        CAST(AVG(wip_now) OVER () AS DOUBLE) AS mu_wip,
        NULLIF(CAST(STDDEV_POP(wip_now) OVER () AS DOUBLE), 0.0) AS sd_wip,
        CAST(AVG(net_7d) OVER () AS DOUBLE) AS mu_net,
        NULLIF(CAST(STDDEV_POP(net_7d) OVER () AS DOUBLE), 0.0) AS sd_net,
        CAST(AVG(p90_dwell_hours) OVER () AS DOUBLE) AS mu_p90,
        NULLIF(CAST(STDDEV_POP(p90_dwell_hours) OVER () AS DOUBLE), 0.0) AS sd_p90
    FROM base
),
scored AS (
    SELECT
        stage_order,
        step_label,
        wip_now,
        inflow_7d,
        outflow_7d,
        net_7d,
        p50_dwell_hours,
        p90_dwell_hours,
        aging_0_24h,
        aging_1_3d,
        aging_3_7d,
        aging_7d_plus,
        (
            COALESCE((wip_now - mu_wip) / sd_wip, 0.0)
            + 1.5 * COALESCE((net_7d - mu_net) / sd_net, 0.0)
            + COALESCE((p90_dwell_hours - mu_p90) / sd_p90, 0.0)
        ) AS bottleneck_score
    FROM zs
)
SELECT *
FROM scored
ORDER BY bottleneck_score DESC, wip_now DESC, stage_order;


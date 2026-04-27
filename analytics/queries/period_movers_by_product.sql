-- Movers (unique apps with ≥1 transition in window), broken down by each app's product type (first product row).

WITH cohort AS (
    SELECT DISTINCT application_id
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
),
movers AS (
    SELECT DISTINCT t.application_id
    FROM v_transitions AS t
    INNER JOIN cohort AS c ON c.application_id = t.application_id
    WHERE t.transition_at::DATE BETWEEN {{PERIOD_START_DATE}} AND {{PERIOD_END_DATE}}
),
app_product AS (
    SELECT
        a.application_id,
        a.product_type
    FROM audit_logs AS a
    INNER JOIN movers AS m ON m.application_id = a.application_id
    WHERE {{PRODUCT_TYPE_FILTER}}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY a.application_id
        ORDER BY a.timestamp ASC, a.action ASC
    ) = 1
)
SELECT
    COALESCE(product_type, 'Unknown') AS product_type,
    COUNT(*)::BIGINT AS n_movers
FROM app_product
GROUP BY 1
ORDER BY n_movers DESC, product_type;

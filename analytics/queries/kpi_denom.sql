WITH filtered AS (
    SELECT *
    FROM audit_logs
    WHERE {{PRODUCT_TYPE_FILTER}}
      AND {{DATE_RANGE_FILTER}}
)
SELECT COUNT(DISTINCT application_id)::BIGINT AS n FROM filtered;

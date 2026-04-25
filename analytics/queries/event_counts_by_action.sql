-- Volume of audit events by action, optionally scoped by product_type.
SELECT
    action,
    COUNT(*)::BIGINT AS event_count
FROM audit_logs
WHERE 1 = 1
  AND {{PRODUCT_TYPE_FILTER}}
  AND {{DATE_RANGE_FILTER}}
GROUP BY action
ORDER BY event_count DESC;

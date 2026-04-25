-- Full audit trail for one application (drill-down), oldest → newest.
SELECT
    application_id,
    timestamp,
    actor,
    action,
    description,
    context
FROM audit_logs
WHERE {{APP_ID_FILTER}}
  AND {{PRODUCT_TYPE_FILTER}}
ORDER BY timestamp ASC, action ASC;

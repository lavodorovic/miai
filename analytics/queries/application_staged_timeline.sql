-- Staged events for an application (for Gantt / timeline in App investigator).
-- Ordered for segment construction in the app layer.

SELECT
    application_id,
    timestamp,
    stage_order,
    action,
    actor
FROM v_audit_staged
WHERE {{APP_ID_FILTER}}
  AND {{PRODUCT_TYPE_FILTER}}
ORDER BY timestamp ASC, action ASC;

-- Team classification per audit row.
-- Purpose: enable "who has the ball", team workload, and SLA slices without duplicating logic in Python.
--
-- Notes:
-- - We keep this view intentionally simple and deterministic.
-- - Prefer action-driven classification; actor-only fallbacks exist for safety.
-- - Customer emails in synthetic data are gmail-style; production may differ.

CREATE OR REPLACE VIEW v_team AS
SELECT
    timestamp,
    actor,
    action,
    application_id,
    product_type,
    CASE
        WHEN action LIKE 'COMPLIANCE_%' THEN 'Compliance'
        WHEN action IN (
            'CUSTOMER_RELATION_REVIEW_STARTED',
            'CUSTOMER_RELATION_REVIEW_COMPLETED',
            'CUSTOMER_RELATION_INTERACTION_STARTED',
            'CUSTOMER_RELATION_INTERACTION_CANCELLED',
            'INTERACTION_STARTED',
            'INTERACTION_SUBMITTED',
            'ANSWERS_EDIT_STARTED',
            'ANSWERS_EDIT_FINISHED',
            'LABEL_ADDED',
            'OFFER_PREPARED',
            'OFFER_SENT',
            'ACCOUNT_MANAGER_ASSIGNED',
            'APP_ASSIGNED'
        ) THEN 'CR'
        WHEN actor = 'N.A. SYSTEM ACTION' THEN 'System'
        WHEN actor LIKE '%@relio.ch' THEN 'CR'
        ELSE 'Customer'
    END AS team
FROM audit_logs;


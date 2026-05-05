-- Weekly series for overview performance: new applications, terminal outcomes,
-- accounts opened (MASTER_DATA_SUBMITTED). Week buckets from audit timestamps.

SELECT
    DATE_TRUNC('week', timestamp)::DATE AS week_start,
    COUNT(DISTINCT CASE WHEN action = 'APPLICATION_STARTED' THEN application_id END)::BIGINT AS n_new_applications,
    COUNT(DISTINCT CASE
        WHEN action IN (
            'MASTER_DATA_SUBMITTED',
            'APPLICATION_REJECTED',
            'APPLICATION_CANCELLED',
            'OFFER_REFUSED'
        ) THEN application_id
    END)::BIGINT AS n_terminal_phase,
    COUNT(DISTINCT CASE WHEN action = 'MASTER_DATA_SUBMITTED' THEN application_id END)::BIGINT AS n_accounts_opened
FROM audit_logs
WHERE {{PRODUCT_TYPE_FILTER}}
  AND {{DATE_RANGE_FILTER}}
GROUP BY 1
ORDER BY 1;

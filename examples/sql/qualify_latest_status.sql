-- QUALIFY keeps the latest status event per customer. It filters after the window function,
-- so the output columns are exactly the SELECT list and the customer key is proven unique.
INSERT OVERWRITE TABLE mart.customer_latest_status
SELECT
    e.customer_id,
    e.customer_status,
    e.event_time
FROM ods.customer_status_event e
WHERE e.dt = '${bizdate}'
QUALIFY ROW_NUMBER() OVER (PARTITION BY e.customer_id ORDER BY e.event_time DESC) = 1;

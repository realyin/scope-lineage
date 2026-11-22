-- The CTE's WHERE runs before its projection, so `e.customer_status = 1` filters the
-- source column, not the ROW_NUMBER the projection names the same way: the CTE ranks
-- rows and keeps every one of them.
WITH ranked_status AS (
    SELECT
        e.customer_id,
        e.event_time,
        ROW_NUMBER() OVER (PARTITION BY e.customer_id ORDER BY e.event_time DESC) AS customer_status
    FROM ods.customer_status_event e
    WHERE e.customer_status = 1
      AND e.dt = '${bizdate}'
)
INSERT OVERWRITE TABLE mart.customer_status_rank
SELECT customer_id, event_time, customer_status AS status_rank
FROM ranked_status;

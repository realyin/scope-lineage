-- JOIN ... USING merges the key column. Spark outputs the left key for INNER and LEFT
-- joins, the right key for RIGHT, and a coalesce of both only for FULL OUTER; a later
-- USING join of the same column matches that carried key.
INSERT OVERWRITE TABLE mart.customer_order_using
SELECT
    customer_id,
    b.customer_name,
    o.pay_amount,
    e.customer_status
FROM ods.customer_base b
LEFT JOIN dwd.order_detail o USING (customer_id)
LEFT JOIN ods.customer_status_event e USING (customer_id)
WHERE customer_id IS NOT NULL
  AND b.dt = '${bizdate}';

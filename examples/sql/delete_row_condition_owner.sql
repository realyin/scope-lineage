-- Unqualified columns in a DELETE condition over a join. `customer_name` belongs to one
-- of the joined tables, which the metadata settles; `dt` belongs to both, so its owner
-- stays unknown: it gets no name and is a row_condition_source_unresolved gap.
INSERT OVERWRITE TABLE mart.order_cleanup
SELECT order_id, customer_id, pay_amount, dt
FROM dwd.order_detail
WHERE dt = '${bizdate}';

DELETE FROM mart.order_cleanup
WHERE EXISTS (
    SELECT 1
    FROM ods.app_order a
    JOIN ods.customer_base b ON a.customer_id = b.customer_id
    WHERE customer_name = 'TEST'
);

DELETE FROM mart.order_cleanup
WHERE EXISTS (
    SELECT 1
    FROM ods.app_order a
    JOIN ods.customer_base b ON a.customer_id = b.customer_id
    WHERE dt = '${bizdate}'
);

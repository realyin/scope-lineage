-- A bare column in a correlated subquery that the subquery's own table does not have.
-- Spark resolves it as an outer reference: `currency_code` is not a column of
-- ods.customer_base, so it is dwd.order_detail's; in the DELETE, `pay_amount` is the
-- written table's.
INSERT OVERWRITE TABLE mart.order_cleanup
SELECT d.order_id, d.customer_id, d.pay_amount, d.dt
FROM dwd.order_detail d
WHERE EXISTS (
    SELECT 1
    FROM ods.customer_base b
    WHERE b.customer_id = d.customer_id AND currency_code = 'USD'
);

DELETE FROM mart.order_cleanup
WHERE EXISTS (
    SELECT 1
    FROM ods.customer_base b
    WHERE b.customer_id = mart.order_cleanup.customer_id AND pay_amount < 0
);

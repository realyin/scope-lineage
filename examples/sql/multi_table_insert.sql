-- Hive multi-table insert: one FROM clause read once, several targets written.
-- It is split before parsing into one INSERT ... SELECT ... FROM per target
-- (warning multi_table_insert_split); each branch keeps its own WHERE / GROUP BY.
FROM dwd.order_detail o
INSERT OVERWRITE TABLE mart.paid_orders PARTITION (dt = '${bizdate}')
SELECT o.order_id, o.customer_id, o.pay_amount
WHERE o.pay_status = 'PAID' AND o.dt = '${bizdate}'
INSERT OVERWRITE TABLE mart.customer_order_cnt PARTITION (dt = '${bizdate}')
SELECT o.customer_id, COUNT(o.order_id) AS order_cnt
WHERE o.dt = '${bizdate}'
GROUP BY o.customer_id;

-- Named windows: the partition and order live in the WINDOW clause, and w_running builds on
-- w_customer. Each OVER reads the columns of the window it names.
INSERT OVERWRITE TABLE mart.customer_order_rank
SELECT
    o.customer_id,
    o.order_id,
    ROW_NUMBER() OVER w_customer AS order_seq,
    SUM(o.pay_amount) OVER w_running AS running_pay_amount
FROM dwd.order_detail o
WHERE o.dt = '${bizdate}'
WINDOW w_customer AS (PARTITION BY o.customer_id ORDER BY o.paid_at),
       w_running AS (w_customer ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

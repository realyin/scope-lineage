-- MAX_BY over a STRUCT picks each customer's latest order; a member taken from it is that
-- order's value, so it still depends on the paid_at that chose the row.
INSERT OVERWRITE TABLE mart.customer_latest_order
WITH latest AS (
    SELECT
        o.customer_id,
        MAX_BY(NAMED_STRUCT('order_id', o.order_id, 'pay_amount', o.pay_amount), o.paid_at) AS last_order
    FROM dwd.order_detail o
    WHERE o.dt = '${bizdate}'
    GROUP BY o.customer_id
)
SELECT
    latest.customer_id,
    latest.last_order.order_id AS last_order_id,
    latest.last_order.pay_amount AS last_pay_amount
FROM latest;

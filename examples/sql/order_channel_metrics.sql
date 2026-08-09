INSERT OVERWRITE TABLE mart.order_channel_metrics
PARTITION (dt = '${bizdate}')
WITH normalized_orders AS (
    SELECT
        order_id,
        customer_id,
        pay_amount,
        pay_status,
        created_at,
        'APP' AS order_channel
    FROM ods.app_order
    WHERE dt = '${bizdate}'

    UNION ALL

    SELECT
        web_order_id AS order_id,
        buyer_id AS customer_id,
        order_amount AS pay_amount,
        order_status AS pay_status,
        order_time AS created_at,
        'WEB' AS order_channel
    FROM ods.web_order
    WHERE dt = '${bizdate}'
)
SELECT
    order_channel,
    COUNT(*) AS order_count,
    COUNT(DISTINCT customer_id) AS customer_count,
    SUM(CASE WHEN pay_status = 'PAID' THEN pay_amount ELSE 0 END) AS paid_amount,
    MIN(created_at) AS first_order_time,
    MAX(created_at) AS last_order_time
FROM normalized_orders
GROUP BY order_channel;

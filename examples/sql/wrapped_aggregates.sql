-- Aggregates wrapped in another function still collapse rows to the GROUP BY grain.
INSERT OVERWRITE TABLE mart.customer_payment_stats
SELECT
    customer_id,
    ROUND(STDDEV(pay_amount), 2) AS pay_amount_stddev,
    COALESCE(MAX_BY(pay_status, paid_at), 'UNKNOWN') AS latest_pay_status,
    ROUND(PERCENTILE_APPROX(pay_amount, 0.5), 2) AS pay_amount_median
FROM dwd.order_detail
WHERE dt = '${bizdate}'
GROUP BY customer_id;

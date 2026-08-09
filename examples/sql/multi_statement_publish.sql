INSERT OVERWRITE TABLE mart.daily_customer_count
PARTITION (dt = '${bizdate}')
SELECT
    country_code,
    COUNT(DISTINCT customer_id) AS customer_count
FROM ods.customer_base
WHERE dt = '${bizdate}'
GROUP BY country_code;

INSERT OVERWRITE TABLE mart.daily_paid_revenue
PARTITION (dt = '${bizdate}')
SELECT
    currency_code,
    SUM(pay_amount) AS paid_amount
FROM dwd.order_detail
WHERE dt = '${bizdate}'
  AND pay_status = 'PAID'
GROUP BY currency_code;

-- 任务：客户画像快照（每日全量重写当日分区）
-- 口径：近 30 天订单指标只计已支付订单
INSERT OVERWRITE TABLE mart.customer_profile_snapshot
PARTITION (dt = '${bizdate}')
WITH latest_status AS (
    SELECT
        customer_id,
        customer_status,
        ROW_NUMBER() OVER (
            PARTITION BY customer_id
            ORDER BY event_time DESC
        ) AS row_num
    FROM ods.customer_status_event
    WHERE dt = '${bizdate}'
),
order_summary AS (
    SELECT
        customer_id,
        COUNT(DISTINCT order_id) AS order_count_30d,
        SUM(CASE WHEN pay_status = 'PAID' THEN pay_amount ELSE 0 END) AS paid_amount_30d,
        MAX(paid_at) AS last_paid_at
    FROM dwd.order_detail
    WHERE dt BETWEEN DATE_SUB('${bizdate}', 29) AND '${bizdate}'
    GROUP BY customer_id
)
SELECT
    base.customer_id,
    COALESCE(base.customer_name, 'UNKNOWN') AS customer_name,
    base.country_code,
    CASE
        WHEN COALESCE(summary.paid_amount_30d, 0) >= 10000 THEN 'HIGH'
        WHEN COALESCE(summary.paid_amount_30d, 0) >= 1000 THEN 'MEDIUM'
        ELSE 'STANDARD'
    END AS customer_level,
    COALESCE(status.customer_status, 'NEW') AS customer_status,
    COALESCE(summary.order_count_30d, 0) AS order_count_30d,
    COALESCE(summary.paid_amount_30d, 0) AS paid_amount_30d, -- 近 30 天已支付金额（元）
    summary.last_paid_at
FROM ods.customer_base base
LEFT JOIN latest_status status
    ON base.customer_id = status.customer_id -- 按客户号取最新一条状态
   AND status.row_num = 1
LEFT JOIN order_summary summary
    ON base.customer_id = summary.customer_id
WHERE base.dt = '${bizdate}';

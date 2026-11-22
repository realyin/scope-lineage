-- PIVOT keeps customer_id as its implicit grouping column and turns each pay status into a
-- column per aggregate (<value>_<alias>); each pivoted column also depends on pay_status.
INSERT OVERWRITE TABLE mart.customer_pay_status_pivot
SELECT *
FROM (
    SELECT o.customer_id, o.pay_status, o.pay_amount, o.order_id
    FROM dwd.order_detail o
    WHERE o.dt = '${bizdate}'
) PIVOT (
    SUM(pay_amount) AS amt,
    COUNT(order_id) AS cnt
    FOR pay_status IN ('PAID' AS paid, 'REFUND' AS refund)
);

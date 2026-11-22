-- CUBE / ROLLUP / GROUPING SETS keep their keys outside the plain GROUP BY list.
-- The scope records grouping_kind, and the profile does not prove these keys unique:
-- subtotal rows carry NULL in the rolled-up keys.
INSERT OVERWRITE TABLE mart.order_amount_cube
SELECT currency_code, pay_status, SUM(pay_amount) AS pay_amount
FROM dwd.order_detail
WHERE dt = '${bizdate}'
GROUP BY CUBE(currency_code, pay_status);

INSERT OVERWRITE TABLE mart.order_amount_rollup
SELECT customer_id, currency_code, COUNT(order_id) AS order_cnt
FROM dwd.order_detail
WHERE dt = '${bizdate}'
GROUP BY GROUPING SETS ((customer_id, currency_code), (customer_id));

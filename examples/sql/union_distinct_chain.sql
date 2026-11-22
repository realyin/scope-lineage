-- A UNION without ALL de-duplicates, and is labelled UNION rather than UNION_ALL.
-- In a mixed chain the label follows the operator that produces each part:
-- here the DISTINCT pair keeps its own set-operation scope under the UNION ALL.
INSERT OVERWRITE TABLE mart.order_buyers
SELECT customer_id, pay_status FROM ods.app_order WHERE dt = '${bizdate}'
UNION
SELECT buyer_id, order_status FROM ods.web_order WHERE dt = '${bizdate}'
UNION ALL
SELECT customer_id, pay_status FROM dwd.order_detail WHERE dt = '${bizdate}';

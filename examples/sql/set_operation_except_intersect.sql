-- EXCEPT and INTERSECT take their values from the left input only.
-- The right input decides which left rows survive; it is reported as a
-- set_operation_semantics_partial gap, never as a value source.
INSERT OVERWRITE TABLE mart.app_only_buyers
SELECT customer_id, pay_status
FROM ods.app_order
WHERE dt = '${bizdate}'
EXCEPT
SELECT buyer_id, order_status
FROM ods.web_order
WHERE dt = '${bizdate}';

INSERT OVERWRITE TABLE mart.cross_channel_buyers
SELECT customer_id
FROM ods.app_order
WHERE dt = '${bizdate}'
INTERSECT
SELECT buyer_id
FROM ods.web_order
WHERE dt = '${bizdate}';

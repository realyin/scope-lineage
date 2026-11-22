-- A MERGE whose action writes a constant: the USING relation is read only by the ON
-- and WHEN conditions, which decide the rows the constant is written to.
MERGE INTO mart.customer_flag AS target
USING (
    SELECT customer_id, customer_status
    FROM ods.customer_status_event
    WHERE dt = '${bizdate}'
) AS source
ON target.customer_id = source.customer_id
WHEN MATCHED AND source.customer_status = 'CLOSED' THEN UPDATE SET target.is_active = 0;

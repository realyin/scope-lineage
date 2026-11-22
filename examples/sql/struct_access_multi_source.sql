-- `contact.addr.city` written without a table alias, in a SELECT over two tables: the
-- first part is the struct column, owned by the one input that has it.
INSERT OVERWRITE TABLE mart.customer_city
SELECT
    b.customer_id,
    contact.addr.city AS city
FROM ods.customer_base b
JOIN ods.customer_contact c ON b.customer_id = c.customer_id
WHERE b.dt = '${bizdate}';

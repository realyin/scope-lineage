-- A three-segment STRUCT path read through a table alias (`c.contact.addr.city`), also in the
-- filter: the value comes from the struct column `contact`, and the member names `addr` and
-- `city` are not table aliases, so the trace is complete.
INSERT OVERWRITE TABLE mart.customer_city
SELECT
    c.customer_id,
    c.contact.addr.city AS city,
    c.contact.addr.zip AS zip
FROM ods.customer_contact c
WHERE c.contact.addr.city IS NOT NULL;

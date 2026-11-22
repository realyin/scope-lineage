-- LATERAL VIEW generators without column aliases: Spark names JSON_TUPLE's outputs
-- c0, c1, ... and STACK's col0, col1, ...
INSERT OVERWRITE TABLE mart.customer_contact_fields
SELECT
    c.customer_id,
    j.c0 AS channel,
    j.c1 AS city,
    s.col0 AS field_name,
    s.col1 AS field_value
FROM ods.customer_contact c
LATERAL VIEW JSON_TUPLE(c.contact_json, 'channel', 'city') j
LATERAL VIEW STACK(2, 'channel', j.c0, 'city', j.c1) s
WHERE c.dt = '${bizdate}';

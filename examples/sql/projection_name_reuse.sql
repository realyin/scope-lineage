-- A later projection names a source column that an earlier alias in the same SELECT also uses.
-- Spark reads the source column first; only a name no input has is a lateral column alias.
INSERT OVERWRITE TABLE mart.order_status_audit
SELECT
    o.order_id,
    currency_code AS pay_status,
    pay_status AS currency_code,
    pay_status || '_FLAG' AS pay_status_tag,
    pay_status_tag || '_V1' AS pay_status_tag_v1,
    pay_amount * 100 AS pay_amount_cents,
    pay_amount_cents / 100 AS pay_amount_check
FROM dwd.order_detail o
WHERE o.dt = '${bizdate}';

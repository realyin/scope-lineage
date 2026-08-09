MERGE INTO mart.customer_profile_current AS target
USING (
    SELECT
        customer_id,
        customer_name,
        country_code,
        updated_at
    FROM ods.customer_change_event
    WHERE dt = '${bizdate}'
) AS source
ON target.customer_id = source.customer_id
WHEN MATCHED AND source.updated_at >= target.updated_at THEN UPDATE SET
    target.customer_name = source.customer_name,
    target.country_code = source.country_code,
    target.updated_at = source.updated_at
WHEN NOT MATCHED THEN INSERT (
    customer_id,
    customer_name,
    country_code,
    updated_at
) VALUES (
    source.customer_id,
    source.customer_name,
    source.country_code,
    source.updated_at
);

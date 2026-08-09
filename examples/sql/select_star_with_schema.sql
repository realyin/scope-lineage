INSERT OVERWRITE TABLE mart.customer_snapshot
SELECT
    source.*
FROM ods.customer_base source
WHERE source.dt = '${bizdate}';

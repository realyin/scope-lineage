INSERT OVERWRITE TABLE mart.user_snapshot
SELECT
    s.*
FROM ods.users s
WHERE s.dt = '2026-01-01';

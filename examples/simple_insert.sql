INSERT OVERWRITE TABLE mart.user_summary
WITH active_users AS (
    SELECT
        u.id,
        u.country,
        u.created_at
    FROM ods.users u
    WHERE u.status = 'active'
)
SELECT
    id AS user_id,
    country,
    TO_DATE(created_at) AS signup_date
FROM active_users;

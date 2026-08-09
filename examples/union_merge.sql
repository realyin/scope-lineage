MERGE INTO mart.user_profile t
USING (
    SELECT id, country, updated_at FROM ods.user_profile_updates
    UNION ALL
    SELECT user_id AS id, region AS country, event_time AS updated_at
    FROM ods.user_region_events
) s
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET
    t.country = s.country,
    t.updated_at = s.updated_at
WHEN NOT MATCHED THEN INSERT (id, country, updated_at)
VALUES (s.id, s.country, s.updated_at);

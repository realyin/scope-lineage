-- `dt` is a column of both joined tables, so the reference is ambiguous; both tables are
-- still inputs this statement reads, and `dt` a column it uses on each.
INSERT OVERWRITE TABLE mart.customer_contact_dates
SELECT b.customer_id, dt
FROM ods.customer_base b
CROSS JOIN ods.customer_contact c;

SET spark.sql.adaptive.enabled = true;

INSERT OVERWRITE TABLE demo_mart.subscription_account_snapshot PARTITION(snapshot_date, processing_source)
SELECT
  t1.subscription_id AS subscription_id,
  t1.service_plan_code AS service_plan_code,
  t1.currency_code AS currency_code,
  t1.snapshot_record_id AS snapshot_id,
  t1.signup_request_id AS signup_request_id,
  CASE
    WHEN t1.service_plan_code = 'DEMO_PROVIDER'
    THEN 'ACTIVE_RECORD'
    WHEN t18.source_system_code = 'billing_primary'
    THEN 'ENABLED'
  END AS billing_account_type,
  CASE
    WHEN COALESCE(t1.parent_subscription_id, '') <> ''
    AND CONCAT(
      '|',
      IF(
        CONCAT_WS('|', t3.hold_reason_codes, t4.hold_reason_codes) = '',
        NULL,
        CONCAT_WS('|', t3.hold_reason_codes, t4.hold_reason_codes)
      ),
      '|'
    ) RLIKE '\\|PLAN_C\\||\\|PLAN_B\\||\\|PLAN_A\\|'
    THEN CEIL(t7.base_charge_balance)
    WHEN COALESCE(t1.parent_subscription_id, '') <> ''
    THEN t7.lifetime_service_amount
    ELSE t2.standard_spending_cap
  END AS standard_spending_cap,
  t2.bonus_spending_cap AS bonus_spending_cap,
  t2.temporary_cap_start_date AS temporary_cap_start_date,
  t2.temporary_cap_end_date AS temporary_cap_end_date,
  t2.temporary_spending_cap AS temporary_spending_cap,
  t7.base_charge_balance AS consumed_spending_cap,
  t1.invoice_day AS invoice_day,
  CONCAT(
    '|',
    IF(
      CONCAT_WS('|', t3.hold_reason_codes, t4.hold_reason_codes) = '',
      NULL,
      CONCAT_WS('|', t3.hold_reason_codes, t4.hold_reason_codes)
    ),
    '|'
  ) AS hold_reason_codes,
  CASE
    WHEN t18.source_system_code = 'billing_primary'
    THEN t15.provider_id
    ELSE t1.signup_channel_code
  END AS signup_channel_code,
  t1.signup_device_type AS signup_device_type,
  t1.service_start_date AS service_start_date,
  t1.service_end_date AS service_end_date,
  'DEMO_VALUE_001' AS payment_method_type,
  t5.payment_provider_id AS payment_provider_id,
  t5.payment_provider_name AS payment_provider_name,
  t5.payment_region_code AS payment_region_code,
  t5.payment_city_code AS payment_city_code,
  t5.payment_account_token AS payment_account_token,
  t5.payment_account_label AS payment_account_label,
  t1.previous_invoice_date AS invoice_date,
  t1.previous_payment_due_date AS payment_due_date,
  CASE
    WHEN COALESCE(t1.previous_invoice_date, '') <> ''
    THEN t6a.grace_period_end_date
    ELSE DATE_ADD(t1.first_payment_due_date, CAST(t1.grace_period_days AS INT))
  END AS grace_period_end_date,
  t1.service_close_date AS service_close_date,
  t1.warning_period_start_date AS warning_period_start_date,
  t1.past_due_start_date AS past_due_start_date,
  COALESCE(t16.past_due_amount_primary, 0) + COALESCE(t17.past_due_amount_secondary, 0) AS past_due_amount,
  t7.past_due_base_charge AS past_due_base_amount,
  COALESCE(t7.current_service_balance, 0) + COALESCE(t17.subscription_scheduled_charge, 0) + COALESCE(t17.subscription_accrued_charge, 0) AS special_charge_balance,
  t7.base_charge_balance AS special_base_charge,
  t1.subscription_purpose AS subscription_purpose,
  CAST(t1.parent_subscription_id AS BIGINT) AS parent_billing_account_id,
  t1.parent_subscription_id AS parent_subscription_id,
  t10.annual_service_rate AS annual_service_rate,
  t12.daily_service_charge_rate AS daily_service_charge_rate,
  t1.maximum_past_due_days AS maximum_past_due_days,
  t1.maximum_warning_days AS maximum_warning_days,
  DATEDIFF(t1.next_payment_due_date, t1.next_invoice_date) AS days_after_payment_due,
  t1.grace_period_days AS grace_period_days,
  t1.original_warning_period_start_date AS original_warning_period_start_date,
  t11.allocation_ratio * 0.01 AS cash_usage_cap_ratio,
  t12.flexible_payment_charge_rate AS flexible_payment_charge_rate,
  CURRENT_TIMESTAMP() AS processed_at,
  t7.cash_usage_balance AS cash_usage_balance,
  t7.installment_cap_balance AS installment_cap_balance,
  CASE
    WHEN t1.first_payment_due_date = t1.next_payment_due_date
    AND t1.previous_payment_due_date IS NULL
    THEN NULL
    ELSE t6a.prior_payment_due_date
  END AS previous_past_due_date,
  t1.next_invoice_date AS next_invoice_date,
  t1.first_invoice_date AS first_invoice_date,
  CASE
    WHEN NOT t1.parent_subscription_id IS NULL
    THEN 'SUSPENDED'
    WHEN NOT t13a.parent_subscription_id IS NULL
    THEN 'PAST_DUE'
    ELSE NULL
  END AS parent_subscription_flag,
  t1.wallet_open_date AS wallet_open_timestamp,
  t14.extension_date AS extension_processed_at,
  t12.early_payment_charge_rate AS early_payment_charge_rate,
  COALESCE(t7.upcoming_base_charge, 0) + COALESCE(t7.past_due_base_charge, 0) + COALESCE(t7.open_receivable_amount, 0) + COALESCE(t7.accrued_penalty_charge, 0) + COALESCE(t7.accrued_service_charge, 0) + COALESCE(t7.accrued_support_charge, 0) + COALESCE(t7.accrued_base_charge, 0) AS current_due_includes_cycle_charge,
  t1.updated_at AS updated_at,
  t12.monthly_protection_charge_rate AS monthly_protection_charge_rate,
  t12.monthly_protection_fixed_charge AS monthly_protection_fixed_charge,
  t12.service_fixed_charge AS service_fixed_charge,
  t12.installment_charge_rate AS installment_charge_rate,
  t12.installment_fixed_charge AS installment_fixed_charge,
  t12.flexible_payment_package_charge AS flexible_payment_package_charge,
  t15.request_date AS request_date,
  t12.collection_service_fixed_charge AS collection_service_fixed_charge,
  t12.collection_penalty_rate AS collection_penalty_rate,
  t12.cash_usage_charge_rate AS cash_usage_charge_rate,
  t12.cash_usage_fixed_charge AS cash_usage_fixed_charge,
  NULL AS installment_collection_fixed_charge,
  NULL AS usage_installment_base_rate,
  t7.charge_free_usage_balance AS charge_free_usage_balance,
  t7.accrued_usage_charge_balance AS accrued_usage_charge_balance,
  t12.notification_fixed_charge AS notification_fixed_charge,
  t1.cooling_off_days AS cooling_off_days,
  t12.early_close_fixed_charge AS early_close_fixed_charge,
  t12.protection_package_charge_rate AS protection_package_charge_rate,
  t1.original_service_end_date AS original_service_end_date,
  t1.service_close_reason AS service_close_reason,
  t1.invoice_enabled_flag AS invoice_enabled_flag,
  t1.wallet_account_token AS wallet_account_token,
  t1.wallet_open_date AS wallet_open_date,
  t4.attribute_codes AS attribute_codes,
  t1.past_due_status AS past_due_status,
  t1.invoice_mode AS invoice_type,
  t1.pre_extension_past_due_date AS pre_extension_past_due_date,
  t9.total_account_credit AS account_credit_amount,
  t7.lifetime_service_amount AS lifetime_service_amount,
  t13b.service_plan_code AS parent_service_plan_code,
  t1.created_at AS created_at,
  t4.feature_codes AS feature_codes,
  COALESCE(t7.upcoming_base_charge, 0) + COALESCE(t7.past_due_base_charge, 0) + COALESCE(t7.open_receivable_amount, 0) + COALESCE(t7.accrued_penalty_charge, 0) + COALESCE(t7.accrued_late_charge, 0) + COALESCE(t17.subscription_scheduled_charge, 0) + COALESCE(t7.accrued_service_charge, 0) + COALESCE(t7.accrued_support_charge, 0) + COALESCE(t7.accrued_base_charge, 0) AS total_payable_amount,
  t2.usage_cap_status AS spending_cap_status,
  'NEW' AS managed_platform_flag,
  NULL AS managed_platform_name,
  t14.extension_past_due_flag AS extension_past_due_flag,
  COALESCE(t7.current_service_balance, 0) + COALESCE(t17.subscription_scheduled_charge, 0) + COALESCE(t17.subscription_accrued_charge, 0) AS subscription_due_balance,
  t1.usage_cap_id AS usage_cap_id,
  NULL AS provider_service_mode,
  NULL AS subscriber_reference,
  NULL AS flexible_service_flag,
  t1.application_code AS application_code,
  '20250115' AS snapshot_date,
  'billing_secondary' AS processing_source,
  t1.next_payment_due_date AS next_payment_due_date,
  t1.service_close_time AS service_close_time,
  subscriber_segment AS subscriber_tier,
  t1.subscription_status AS subscription_status,
  t1.subscriber_id AS subscriber_id,
  t10.annual_service_rate_history AS annual_service_rate_history,
  t12.daily_service_charge_rate_history AS daily_service_charge_rate_history
FROM (
  SELECT
    *
  FROM demo_ods.subscription_account
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
) AS t1
LEFT JOIN (
  SELECT
    a.subscription_id,
    a.usage_cap_id,
    a.usage_cap_status,
    b.standard_spending_cap,
    b.bonus_spending_cap,
    b.temporary_cap_start_date,
    b.temporary_cap_end_date,
    b.temporary_spending_cap,
    b.consumed_spending_cap,
    b.billing_account_type,
    b.available_spending_cap
  FROM (
    SELECT
      subscription_id,
      usage_cap_id,
      usage_cap_status
    FROM demo_ods.usage_cap
    WHERE
      record_state = 0 AND snapshot_date = '20250115'
  ) AS a
  LEFT JOIN (
    SELECT
      usage_cap_id,
      MAX(CASE WHEN usage_cap_type = '1' THEN standard_spending_cap END) AS standard_spending_cap,
      MAX(CASE WHEN usage_cap_type = '2' THEN standard_spending_cap END) AS bonus_spending_cap,
      MAX(CASE WHEN usage_cap_type = '1' THEN temporary_cap_start_date END) AS temporary_cap_start_date,
      MAX(CASE WHEN usage_cap_type = '1' THEN temporary_cap_end_date END) AS temporary_cap_end_date,
      MAX(
        CASE
          WHEN usage_cap_type = '1' AND temporary_cap_allowed_flag = 1
          THEN temporary_spending_cap
        END
      ) AS temporary_spending_cap,
      MAX(CASE WHEN usage_cap_type = '1' THEN consumed_spending_cap END) AS consumed_spending_cap,
      MAX(
        CASE
          WHEN usage_cap_type = '1' AND reusable_cap_flag = 0 AND multi_use_flag = 1
          THEN 'ACTIVE_RECORD'
          WHEN usage_cap_type = '1' AND reusable_cap_flag = 1 AND multi_use_flag = 1
          THEN 'CLOSED'
          WHEN usage_cap_type = '1' AND reusable_cap_flag = 0 AND multi_use_flag = 0
          THEN 'GRACE'
        END
      ) AS billing_account_type,
      MAX(CASE WHEN usage_cap_type = '1' THEN available_spending_cap END) AS available_spending_cap
    FROM demo_ods.usage_cap_balance
    WHERE
      record_state = 0 AND snapshot_date = '20250115'
    GROUP BY
      usage_cap_id
  ) AS b
    ON a.usage_cap_id = b.usage_cap_id
) AS t2
  ON t1.subscription_id = t2.subscription_id
LEFT JOIN (
  SELECT
    usage_cap_id,
    IF(
      CONCAT_WS('|', COLLECT_SET(hold_reason_code)) = '',
      NULL,
      CONCAT_WS('|', COLLECT_SET(hold_reason_code))
    ) AS hold_reason_codes
  FROM demo_ods.usage_cap_hold
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
  GROUP BY
    usage_cap_id
) AS t3
  ON t2.usage_cap_id = t3.usage_cap_id
LEFT JOIN (
  SELECT
    subscription_id,
    IF(
      CONCAT_WS('|', COLLECT_SET(CASE WHEN attribute_type = '2' THEN attribute_value END)) = '',
      NULL,
      CONCAT_WS('|', COLLECT_SET(CASE WHEN attribute_type = '2' THEN attribute_value END))
    ) AS hold_reason_codes,
    CONCAT(
      '|',
      IF(
        CONCAT_WS('|', COLLECT_SET(CASE WHEN attribute_type = '1' THEN attribute_value END)) = '',
        NULL,
        CONCAT_WS('|', COLLECT_SET(CASE WHEN attribute_type = '1' THEN attribute_value END))
      ),
      '|'
    ) AS attribute_codes,
    IF(
      CONCAT_WS('|', COLLECT_SET(CASE WHEN attribute_type = '3' THEN attribute_value END)) = '',
      NULL,
      CONCAT_WS('|', COLLECT_SET(CASE WHEN attribute_type = '3' THEN attribute_value END))
    ) AS feature_codes
  FROM demo_ods.subscription_attribute
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
  GROUP BY
    subscription_id
) AS t4
  ON t1.subscription_id = t4.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    payment_provider_id,
    payment_provider_name,
    payment_region_code,
    payment_city_code,
    payment_account_token AS payment_account_token,
    payment_account_label AS payment_account_label
  FROM demo_ods.payment_method
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
) AS t5
  ON t1.subscription_id = t5.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    invoice_date,
    grace_period_end_date,
    minimum_payment_amount,
    LAG(payment_due_date, 1, NULL) OVER (PARTITION BY subscription_id ORDER BY invoice_date) AS prior_payment_due_date
  FROM demo_ods.subscription_invoice_schedule
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
) AS t6a
  ON t1.subscription_id = t6a.subscription_id
  AND t1.previous_invoice_date = t6a.invoice_date
LEFT JOIN (
  SELECT
    a.subscription_id,
    SUM(b.base_charge_balance) AS base_charge_balance,
    SUM(b.upcoming_base_charge) AS upcoming_base_charge,
    SUM(b.past_due_base_charge) AS past_due_base_charge,
    SUM(
      CASE
        WHEN a.installment_end_type <> '0'
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0) + COALESCE(b.accrued_penalty_charge, 0) + COALESCE(b.accrued_late_charge, 0) + COALESCE(b.accrued_base_charge, 0) + COALESCE(b.accrued_service_charge, 0) + COALESCE(b.accrued_support_charge, 0)
        ELSE COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0) + COALESCE(b.accrued_penalty_charge, 0) + COALESCE(b.accrued_late_charge, 0) + COALESCE(b.accrued_service_charge, 0) + COALESCE(b.accrued_support_charge, 0) + COALESCE(b.accrued_base_charge, 0)
      END
    ) AS current_service_balance,
    SUM(
      CASE
        WHEN a.billing_account_type IN ('4', '5') AND a.installment_end_type <> '0'
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0) + COALESCE(b.accrued_penalty_charge, 0) + COALESCE(b.accrued_late_charge, 0) + COALESCE(b.accrued_base_charge, 0)
        WHEN a.billing_account_type IN ('4', '5')
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0) + COALESCE(b.accrued_penalty_charge, 0) + COALESCE(b.accrued_late_charge, 0) + COALESCE(b.accrued_base_charge, 0)
      END
    ) AS cash_usage_balance,
    SUM(
      CASE
        WHEN a.billing_account_type IN ('3', '4') AND a.installment_end_type <> '0'
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0) + COALESCE(b.accrued_penalty_charge, 0) + COALESCE(b.accrued_late_charge, 0) + COALESCE(b.accrued_base_charge, 0)
        WHEN a.billing_account_type IN ('3', '4')
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0) + COALESCE(b.accrued_penalty_charge, 0) + COALESCE(b.accrued_late_charge, 0) + COALESCE(b.accrued_base_charge, 0)
      END
    ) AS installment_cap_balance,
    SUM(
      CASE
        WHEN a.billing_account_type = '2'
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0)
      END
    ) AS charge_free_usage_balance,
    SUM(
      CASE
        WHEN a.billing_account_type = '1'
        THEN COALESCE(b.base_charge_balance, 0) + COALESCE(b.open_receivable_amount, 0)
      END
    ) AS accrued_usage_charge_balance,
    SUM(
      CASE
        WHEN COALESCE(a.converted_billing_account_id, '') = ''
        THEN a.original_service_amount
      END
    ) AS lifetime_service_amount,
    SUM(b.open_receivable_amount) AS open_receivable_amount,
    SUM(b.accrued_penalty_charge) AS accrued_penalty_charge,
    SUM(b.accrued_late_charge) AS accrued_late_charge,
    SUM(b.accrued_service_charge) AS accrued_service_charge,
    SUM(b.accrued_support_charge) AS accrued_support_charge,
    SUM(b.accrued_base_charge) AS accrued_base_charge
  FROM (
    SELECT
      billing_account_id,
      subscription_id,
      past_due_start_date,
      billing_account_type,
      original_service_amount,
      converted_billing_account_id,
      installment_end_type
    FROM demo_ods.billing_account
    WHERE
      record_state = 0 AND snapshot_date = '20250115'
  ) AS a
  LEFT JOIN (
    SELECT
      billing_account_id,
      SUM(CASE WHEN component_type = 'UPCOMING_BASE_CHARGE' THEN component_amount END) AS upcoming_base_charge,
      SUM(CASE WHEN component_type = 'PAST_DUE_BASE_CHARGE' THEN component_amount END) AS past_due_base_charge,
      SUM(CASE WHEN component_category = 'BASE_CHARGE' THEN component_amount END) AS base_charge_balance,
      SUM(CASE WHEN component_type LIKE 'PAYABLE%' THEN component_amount END) AS open_receivable_amount,
      SUM(CASE WHEN component_type IN ('PENDING_PENALTY_CHARGE') THEN component_amount END) AS accrued_penalty_charge,
      SUM(CASE WHEN component_type IN ('PENDING_LATE_CHARGE') THEN component_amount END) AS accrued_late_charge,
      SUM(CASE WHEN component_type IN ('PENDING_BASE_CHARGE') THEN component_amount END) AS accrued_base_charge,
      SUM(CASE WHEN component_type IN ('PENDING_SERVICE_CHARGE') THEN component_amount END) AS accrued_service_charge,
      SUM(CASE WHEN component_type IN ('PENDING_SUPPORT_CHARGE') THEN component_amount END) AS accrued_support_charge
    FROM demo_ods.billing_balance_component
    WHERE
      record_state = 0 AND snapshot_date = '20250115'
    GROUP BY
      billing_account_id
  ) AS b
    ON a.billing_account_id = b.billing_account_id
  GROUP BY
    a.subscription_id
) AS t7
  ON t1.subscription_id = t7.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    SUM(component_amount) AS total_account_credit,
    SUM(CASE WHEN billing_account_id IS NULL THEN component_amount END) AS subscription_credit,
    SUM(CASE WHEN NOT billing_account_id IS NULL THEN component_amount END) AS billing_account_credit
  FROM demo_ods.account_credit
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
  GROUP BY
    subscription_id
) AS t9
  ON t1.subscription_id = t9.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    MAX(
      CASE
        WHEN service_rate_unit = 'YES'
        THEN service_rate
        WHEN service_rate_unit = 'MANAGED'
        THEN service_rate * 12
        WHEN service_rate_unit = 'DISABLED'
        THEN service_rate * 360
      END
    ) AS annual_service_rate,
    CONCAT_WS(
      ',',
      COLLECT_SET(
        CASE
          WHEN service_rate_unit = 'YES'
          THEN CONCAT(installment_cycles, '-', FORMAT_NUMBER(service_rate, 10))
          WHEN service_rate_unit = 'MANAGED'
          THEN CONCAT(installment_cycles, '-', FORMAT_NUMBER((
            service_rate * 12
          ), 10))
          WHEN service_rate_unit = 'DISABLED'
          THEN CONCAT(installment_cycles, '-', FORMAT_NUMBER((
            service_rate * 360
          ), 10))
        END
      )
    ) AS annual_service_rate_history
  FROM demo_ods.subscription_rate_plan
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
  GROUP BY
    subscription_id
) AS t10
  ON t1.subscription_id = t10.subscription_id
LEFT JOIN (
  SELECT
    usage_cap_id,
    allocation_ratio
  FROM demo_ods.usage_cap_allocation
  WHERE
    usage_cap_type = 1
    AND snapshot_date = '20250115'
    AND billing_account_type IN (4, 5)
    AND cap_allocation_method = 1
    AND record_state = 0
) AS t11
  ON t1.usage_cap_id = t11.usage_cap_id
LEFT JOIN (
  SELECT
    subscription_id,
    MAX(CASE WHEN charge_rule_code = 'RULE_023' THEN charge_rate END) AS installment_charge_rate,
    MAX(
      CASE WHEN charge_rule_code = 'RULE_001' AND billing_cycles = 1 THEN charge_rate END
    ) AS cash_usage_charge_rate,
    MAX(
      CASE
        WHEN charge_rule_code = 'RULE_001' AND billing_cycles = 1
        THEN fixed_charge_amount
      END
    ) AS cash_usage_fixed_charge,
    MAX(
      CASE
        WHEN charge_rule_code = 'RULE_002' AND billing_cycles = 1
        THEN fixed_charge_amount
      END
    ) AS early_close_fixed_charge,
    MAX(
      CASE
        WHEN charge_rule_code = 'RULE_008' AND billing_cycles = 1
        THEN fixed_charge_amount
      END
    ) AS notification_fixed_charge,
    MAX(CASE WHEN charge_rule_code = 'RULE_009' THEN charge_rate END) AS flexible_payment_charge_rate,
    MAX(CASE WHEN charge_rule_code = 'RULE_009' THEN fixed_charge_amount END) AS flexible_payment_package_charge,
    MAX(CASE WHEN charge_rule_code = 'RULE_011' THEN charge_rate END) AS protection_package_charge_rate,
    MAX(CASE WHEN charge_rule_code = 'RULE_017' THEN charge_rate END) AS collection_penalty_rate,
    MAX(
      CASE WHEN charge_rule_code = 'RULE_002' AND billing_cycles = 1 THEN charge_rate END
    ) AS early_payment_charge_rate,
    MAX(CASE WHEN charge_rule_code = 'RULE_004' THEN fixed_charge_amount END) AS collection_service_fixed_charge,
    MAX(CASE WHEN charge_rule_code = 'RULE_016' THEN fixed_charge_amount END) AS service_fixed_charge,
    MAX(CASE WHEN charge_rule_code = 'RULE_016' THEN charge_rate END) AS daily_service_charge_rate,
    MAX(CASE WHEN charge_rule_code = 'RULE_023' THEN fixed_charge_amount END) AS installment_fixed_charge,
    MAX(CASE WHEN charge_rule_code = 'RULE_028' THEN charge_rate END) AS monthly_protection_charge_rate,
    MAX(CASE WHEN charge_rule_code = 'RULE_028' THEN fixed_charge_amount END) AS monthly_protection_fixed_charge,
    CONCAT_WS(
      ',',
      COLLECT_SET(
        CASE
          WHEN charge_rule_code = 'RULE_016'
          THEN CONCAT(billing_cycles, '-', FORMAT_NUMBER(charge_rate, 10))
        END
      )
    ) AS daily_service_charge_rate_history
  FROM demo_ods.subscription_charge_rule
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
  GROUP BY
    subscription_id
) AS t12
  ON t1.subscription_id = t12.subscription_id
LEFT JOIN (
  SELECT
    parent_subscription_id
  FROM demo_ods.subscription_account
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
  GROUP BY
    parent_subscription_id
) AS t13a
  ON t1.subscription_id = t13a.parent_subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    service_plan_code
  FROM demo_ods.subscription_account
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
) AS t13b
  ON (
    CASE
      WHEN NOT t1.parent_subscription_id IS NULL
      THEN t1.parent_subscription_id
      ELSE CONCAT('UNKNOWN@UNKNOWN', t1.subscription_id)
    END
  ) = t13b.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    CASE WHEN extension_past_due_flag = 1 THEN extension_date ELSE NULL END AS extension_date,
    extension_past_due_flag
  FROM demo_ods.subscription_status_change
  WHERE
    record_state = 0 AND snapshot_date = '20250115'
) AS t14
  ON t1.subscription_id = t14.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    SUBSTRING(requested_at, 1, 10) AS request_date,
    provider_id
  FROM demo_ods.subscription_request
  WHERE
    snapshot_date = '20250115'
    AND request_state RLIKE 'ACTIVE|NEW|MIGRATED'
    AND NOT subscription_id IS NULL
) AS t15
  ON COALESCE(t1.parent_subscription_id, t1.subscription_id) = t15.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    SUM(
      COALESCE(scheduled_base_charge, 0) + COALESCE(scheduled_service_charge, 0) + COALESCE(scheduled_penalty_charge, 0) + COALESCE(scheduled_support_charge, 0) + COALESCE(scheduled_charge_amount, 0) + COALESCE(scheduled_late_charge, 0) + COALESCE(accrued_penalty_charge, 0) + COALESCE(accrued_late_charge, 0)
    ) AS past_due_amount_primary
  FROM demo_ods.invoice_receivable_schedule
  WHERE
    snapshot_date = '20250115' AND current_cycle_state = '1' AND record_state = 0
  GROUP BY
    subscription_id
) AS t16
  ON t1.subscription_id = t16.subscription_id
LEFT JOIN (
  SELECT
    subscription_id,
    SUM(
      CASE
        WHEN COALESCE(past_due_start_date, '') <> '' AND COALESCE(settled_date, '') = ''
        THEN scheduled_charge_amount
      END
    ) AS past_due_amount_secondary,
    SUM(scheduled_charge_amount) AS subscription_scheduled_charge,
    SUM(accrued_charge_amount) AS subscription_accrued_charge
  FROM demo_ods.subscription_charge_schedule
  WHERE
    snapshot_date = '20250115' AND record_state = 0
  GROUP BY
    subscription_id
) AS t17
  ON t1.subscription_id = t17.subscription_id
LEFT JOIN (
  SELECT
    service_plan_code,
    MAX(LOWER(source_system_code)) AS source_system_code
  FROM demo_ods.service_route_snapshot
  WHERE
    snapshot_date = '20250115'
    AND record_state = 0
    AND migration_state = '2'
    AND routing_pattern = '2'
  GROUP BY
    service_plan_code
) AS t18
  ON t1.service_plan_code = t18.service_plan_code
LEFT JOIN (
  SELECT
    subscription_id,
    subscriber_segment
  FROM demo_ods.subscriber_segment
  WHERE
    snapshot_date = '20250115'
) AS subscriber_profile
  ON t1.subscription_id = subscriber_profile.subscription_id;

# 公开任务成品补丁验收

类型：`reviewed_patch_acceptance`；补丁来源：`operator_reviewed`。

本报告不属于自主 Agent 试验，未调用模型 API，不产生模型调用数或 token 指标。历史自主执行成绩保持原样。

已接受 3/4 个预登记任务。

验收策略：`upstream_harness`。额外 dbt build 原始结果始终保留；upstream_harness 以真实目标物化和原 pytest 为门槛。

| 任务 | 依赖 run | 目标 build | 原 pytest reward | 补丁验收 |
|---|---|---|---:|---|
| dbt-fix-timezone-sales | True | False | 1.0 | True |
| dbt-fix-daily-revenue | True | True | 1.0 | True |
| dbt-exchange-rate-settlement-date | True | True | 1.0 | True |
| cohort-retention-matrix | False | False | unavailable | False |

## dbt-fix-timezone-sales

Patch SHA-256：`6b31024ac3a6607b96478910246cdaf922030202f761011692adbe17c2cae328`。

当前候选及祖先 run stdout：

```text
{"success": true, "exception": null}

```

原 build stdout：

```text
06:56:29  2 of 4 FAIL 177 not_null_int_sales__orders_enriched_order_id ................... [FAIL 177 in 0.18s]
06:56:29  3 of 4 FAIL 1308 unique_int_sales__orders_enriched_order_id .................... [FAIL 1308 in 0.19s]
06:56:31  [ERROR]: in test not_null_int_sales__orders_enriched_order_id (models\intermediate\schema.yml)
06:56:31    Got 177 results, configured to fail if != 0
06:56:31  [ERROR]: in test unique_int_sales__orders_enriched_order_id (models\intermediate\schema.yml)
06:56:31    Got 1308 results, configured to fail if != 0
{"success": false, "exception": null}

```

原 pytest stdout：

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.1.1, pluggy-1.7.0 -- $PROJECT\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: $PROJECT
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 10 items

test_outputs_timezone.py::test_int_sales_orders_enriched_exists PASSED   [ 10%]
test_outputs_timezone.py::test_int_sales_has_data PASSED                 [ 20%]
test_outputs_timezone.py::test_sap_timestamps_handling PASSED            [ 30%]
test_outputs_timezone.py::test_timezone_alignment_consistency PASSED     [ 40%]
test_outputs_timezone.py::test_daily_aggregation_consistency PASSED      [ 50%]
test_outputs_timezone.py::test_all_timestamps_have_time_component PASSED [ 60%]
test_outputs_timezone.py::test_source_system_distribution PASSED         [ 70%]
test_outputs_timezone.py::test_no_null_timestamps_for_completed_orders PASSED [ 80%]
test_outputs_timezone.py::test_timestamp_ordering PASSED                 [ 90%]
test_outputs_timezone.py::test_model_structure_preserved PASSED          [100%]

============================= 10 passed in 50.97s =============================

```

## dbt-fix-daily-revenue

Patch SHA-256：`f0ff4288c19eabab606c2e7642b53550a8c7cb591b010b42fef0358271c86f99`。

当前候选及祖先 run stdout：

```text
{"success": true, "exception": null}

```

原 build stdout：

```text
{"success": true, "exception": null}

```

原 pytest stdout：

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.1.1, pluggy-1.7.0 -- $PROJECT\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: $PROJECT
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 13 items

test_outputs_daily.py::test_no_missing_dates PASSED                      [  7%]
test_outputs_daily.py::test_zero_revenue_dates_exist PASSED              [ 15%]
test_outputs_daily.py::test_cumulative_revenue_matches_total PASSED      [ 23%]
test_outputs_daily.py::test_cumulative_revenue_monotonic_increasing PASSED [ 30%]
test_outputs_daily.py::test_cumulative_revenue_accuracy_sample_dates PASSED [ 38%]
test_outputs_daily.py::test_date_sequence_continuous PASSED              [ 46%]
test_outputs_daily.py::test_no_null_revenue_values PASSED                [ 53%]
test_outputs_daily.py::test_zero_revenue_days_have_zero_orders PASSED    [ 61%]
test_outputs_daily.py::test_revenue_sum_matches_orders PASSED            [ 69%]
test_outputs_daily.py::test_cumulative_starts_with_first_day_revenue PASSED [ 76%]
test_outputs_daily.py::test_model_structure_preserved PASSED             [ 84%]
test_outputs_daily.py::test_no_duplicate_dates PASSED                    [ 92%]
test_outputs_daily.py::test_cumulative_never_zero_after_first_revenue PASSED [100%]

============================= 13 passed in 2.28s ==============================

```

## dbt-exchange-rate-settlement-date

Patch SHA-256：`4d4523660113a878ae9b2c2a3c3ae021410f886a29e847180415206353f554bc`。

当前候选及祖先 run stdout：

```text
{"success": true, "exception": null}

```

原 build stdout：

```text
{"success": true, "exception": null}

```

原 pytest stdout：

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.1.1, pluggy-1.7.0 -- $PROJECT\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: $PROJECT
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 20 items

test_outputs_fx.py::TestStructure::test_columns_exist PASSED             [  5%]
test_outputs_fx.py::TestStructure::test_settlement_date_not_null PASSED  [ 10%]
test_outputs_fx.py::TestStructure::test_some_rows_have_different_settlement_date PASSED [ 15%]
test_outputs_fx.py::TestStructure::test_grain_matches_expected_keys PASSED [ 20%]
test_outputs_fx.py::TestFxRates::test_usd_identity PASSED                [ 25%]
test_outputs_fx.py::TestFxRates::test_fx_rate_matches_dim PASSED         [ 30%]
test_outputs_fx.py::TestFxRates::test_fx_rate_not_null PASSED            [ 35%]
test_outputs_fx.py::TestFxRates::test_fx_rate_fallback_for_missing_currencies PASSED [ 40%]
test_outputs_fx.py::TestFxRates::test_usd_fields_rounded PASSED          [ 45%]
test_outputs_fx.py::TestFxRates::test_non_usd_rates_not_identity_when_rate_exists PASSED [ 50%]
test_outputs_fx.py::TestFxRates::test_fx_rate_matches_dim_for_all_rows PASSED [ 55%]
test_outputs_fx.py::TestFxRates::test_usd_fx_rate_is_identity PASSED     [ 60%]
test_outputs_fx.py::TestFxConversion::test_usd_totals_match_expected PASSED [ 65%]
test_outputs_fx.py::TestFxConversion::test_uses_settlement_date_rates PASSED [ 70%]
test_outputs_fx.py::TestFxConversion::test_all_rows_match_expected_settlement_fx PASSED [ 75%]
test_outputs_fx.py::TestFxConversion::test_settlement_fx_differs_from_order_fx_for_some_groups PASSED [ 80%]
test_outputs_fx.py::TestFxConversion::test_fx_rate_uses_settlement_date_when_rates_differ PASSED [ 85%]
test_outputs_fx.py::TestFxConversion::test_fx_rate_not_equal_order_rate_when_rates_differ PASSED [ 90%]
test_outputs_fx.py::TestFxConversion::test_usd_metrics_follow_fx_rate PASSED [ 95%]
test_outputs_fx.py::TestSettlementDateFallback::test_no_payment_orders_use_order_date PASSED [100%]

======================== 20 passed in 69.81s (0:01:09) ========================

```

## cohort-retention-matrix

Patch SHA-256：`710afaf955d0bc5d71dd8c44cbf1d45ba7505e392339b5947cd5d1e2fe4184ca`。

当前候选及祖先 run stdout：

```text

```

原 build stdout：

```text

```

原 pytest stdout：

```text

```

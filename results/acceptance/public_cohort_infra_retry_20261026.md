# 公开任务成品补丁验收

类型：`reviewed_patch_acceptance`；补丁来源：`operator_reviewed`。

本报告不属于自主 Agent 试验，未调用模型 API，不产生模型调用数或 token 指标。历史自主执行成绩保持原样。

已接受 1/1 个预登记任务。

验收策略：`upstream_harness`。额外 dbt build 原始结果始终保留；upstream_harness 以真实目标物化和原 pytest 为门槛。

| 任务 | 依赖 run | 目标 build | 原 pytest reward | 补丁验收 |
|---|---|---|---:|---|
| cohort-retention-matrix | True | True | 1.0 | True |

## cohort-retention-matrix

Patch SHA-256：`710afaf955d0bc5d71dd8c44cbf1d45ba7505e392339b5947cd5d1e2fe4184ca`。

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
collecting ... collected 24 items

test_outputs_cohort.py::TestPhase1Structure::test_model_file_exists PASSED [  4%]
test_outputs_cohort.py::TestPhase1Structure::test_model_exists_in_schema PASSED [  8%]
test_outputs_cohort.py::TestPhase1Structure::test_all_required_columns_exist PASSED [ 12%]
test_outputs_cohort.py::TestPhase1Structure::test_has_rows PASSED        [ 16%]
test_outputs_cohort.py::TestPhase1Structure::test_cohort_month_format PASSED [ 20%]
test_outputs_cohort.py::TestPhase2CohortLogic::test_cohort_sizes_match_source PASSED [ 25%]
test_outputs_cohort.py::TestPhase2CohortLogic::test_total_customers_match PASSED [ 29%]
test_outputs_cohort.py::TestPhase2CohortLogic::test_never_ordered_matches_source PASSED [ 33%]
test_outputs_cohort.py::TestPhase2CohortLogic::test_acquisition_source_threshold PASSED [ 37%]
test_outputs_cohort.py::TestPhase2CohortLogic::test_one_row_per_cohort_source PASSED [ 41%]
test_outputs_cohort.py::TestPhase3RetentionCalculations::test_retention_not_higher_than_cohort_size PASSED [ 45%]
test_outputs_cohort.py::TestPhase3RetentionCalculations::test_m0_retention_matches_source PASSED [ 50%]
test_outputs_cohort.py::TestPhase3RetentionCalculations::test_m1_retention_matches_source PASSED [ 54%]
test_outputs_cohort.py::TestPhase3RetentionCalculations::test_retention_rates_calculated_correctly PASSED [ 58%]
test_outputs_cohort.py::TestPhase3RetentionCalculations::test_ltv_calculation_matches PASSED [ 62%]
test_outputs_cohort.py::TestPhase3RetentionCalculations::test_revenue_values_non_negative PASSED [ 66%]
test_outputs_cohort.py::TestPhase4CumulativeAndChurn::test_m1_cumulative_matches_source PASSED [ 70%]
test_outputs_cohort.py::TestPhase4CumulativeAndChurn::test_cumulative_increases_monotonically PASSED [ 75%]
test_outputs_cohort.py::TestPhase4CumulativeAndChurn::test_cumulative_not_higher_than_cohort_size PASSED [ 79%]
test_outputs_cohort.py::TestPhase4CumulativeAndChurn::test_early_churned_matches_source PASSED [ 83%]
test_outputs_cohort.py::TestPhase4CumulativeAndChurn::test_early_churned_not_higher_than_m0_retained PASSED [ 87%]
test_outputs_cohort.py::TestPhase4CumulativeAndChurn::test_avg_days_to_second_purchase_reasonable PASSED [ 91%]
test_outputs_cohort.py::TestPhase5Ordering::test_sorted_correctly PASSED [ 95%]
test_outputs_cohort.py::TestPhase6Idempotency::test_idempotency PASSED   [100%]

======================== 24 passed in 64.67s (0:01:04) ========================

```

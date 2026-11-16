# data-eng-bench 公开开发任务：本地适配实际结果（非官方成绩）

数据集：snowflake-data-eng-bench/native-public-development-subset

Snowflake-Labs/data-eng-bench 固定公开开发题；原始数据、dbt项目和任务说明，Windows native路径适配；非官方Docker/Harbor成绩，非未知保留集。

状态：completed；记录 2/2 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 0/2 | 0.0% | 未做重复实验 | 122.82 | 1672068 | 0.509549 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| dbt-fix-refund-reconciliation | verified | 0 | False | refund-verified-02-verified |
| dbt-fix-division-by-zero | verified | 0 | False | division-verified-01-verified |

## 外部任务验收与限制

固定 commit：`a3278ad102829a6084dde086244a0ef665a8011c`；模型：`deepseek-flash`。

| 任务 | 最大步数 | 停止原因 | 上游组件通过/总数 | 二元reward |
|---|---:|---|---:|---:|
| dbt-fix-refund-reconciliation | 24 | step_limit | 12/13 | 0.0 |
| dbt-fix-division-by-zero | 16 | step_limit | 1/15 | 0.0 |

- Only 2 public development trial(s), one per task; no performance/generalization claim.
- Native Windows/dbt versions and selected-ancestor initialization differ from the official Linux Docker environment.
- Task success requires every upstream component to pass; partial component credit is descriptive only.
- Repeated identical successful SQL queries continued to the model step limit; this behavior is retained.
- No React comparison was run; these are development executions rather than an ablation experiment.

### dbt-fix-refund-reconciliation

原始 pytest 输出（只进行路径重映射，未改测试断言）：

```text
CMD: dbt deps
STDOUT: [0m12:31:34  Running with dbt=1.12.6
[0m12:31:40  Installing dbt-labs/dbt_utils
[0m12:31:43  Installed from version 1.3.3
[0m12:31:43  Updated version available: 1.4.1
[0m12:31:43  
[0m12:31:43  Updates available for packages: ['dbt-labs/dbt_utils']                 
Update your versions in packages.yml, then run dbt deps

CMD: dbt run -s rpt_return_reconciliation
STDOUT: [0m12:31:51  Running with dbt=1.12.6
[0m12:31:51  Registered adapter: duckdb=1.11.0
[0m12:31:55  [[33mWARNING[0m]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 10 unused configuration paths:
- models.retail_warehouse.marts
- models.retail_warehouse.staging.sap
- models.retail_warehouse.staging.payments
- models.retail_warehouse.staging.pos
- models.retail_warehouse.staging.legacy
- models.retail_warehouse.staging
- models.retail_warehouse.intermediate
- models.retail_warehouse.staging.ga
- models.retail_warehouse.staging.wms
- models.retail_warehouse.staging.sfdc
[0m12:31:58  Found 2333 models, 7 snapshots, 60 analyses, 10 seeds, 814 data tests, 1348 sources, 667 macros
[0m12:31:58  
[0m12:31:58  Concurrency: 4 threads (target='dev')
[0m12:31:58  
[0m12:32:00  1 of 1 START sql table model main.rpt_return_reconciliation .................... [RUN]
[0m12:32:00  1 of 1 OK created sql table model main.rpt_return_reconciliation ............... [[32mOK[0m in 0.29s]
[0m12:32:00  
[0m12:32:00  Finished running 1 table model in 0 hours 0 minutes and 2.48 seconds (2.48s).
[0m12:32:02  
[0m12:32:02  [32mCompleted successfully[0m
[0m12:32:02  
[0m12:32:02  Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=1

PASS: component_1_model_compiles
PASS: component_2_no_inf_nan_values
PASS: component_3_row_count
PASS: component_4_required_columns
PASS: component_5_valid_tier_values
PASS: component_6_uses_window_function
PASS: component_7_tier_distribution
FAIL: component_8_waterfall_tier_logic: Tier logic errors:
return 0b5c41ba-0d3d-416e-a354-904ebe30d27f: tier='critical_delay', expected='needs_improvement' (days=11.0, rate=5.32, slow_pct=0.30)
return 16cd0e50-5303-4f95-8d48-b3614beab578: tier='needs_improvement', expected='acceptable' (days=9.0, rate=3.25, slow_pct=0.60)
return 1a775a13-2d9c-41ac-b703-0677339195d0: tier='needs_improvement', expected='acceptable' (days=8.0, rate=5.42, slow_pct=0.74)
return 1cbd3698-5d85-4629-8949-89e53f9f0569: tier='needs_improvement', expected='acceptable' (days=8.0, rate=3.05, slow_pct=0.74)
return 23a9926d-a420-48d5-a831-a9ea0872cd0e: tier='needs_improvement', expected='acceptable' (days=7.0, rate=1.89, slow_pct=0.86)
PASS: component_9_refund_completion_rate_formula
PASS: component_10_no_inf_nan_all_numeric_columns
PASS: component_11_tier_boundary_testing
PASS: component_12_days_non_negative
PASS: component_13_total_processing_days_consistency

Final Score: 0.0
F
================================== FAILURES ===================================
________________________________ test_solution ________________________________

    def test_solution():
        scores = {}
    
        for component_name in WEIGHTS:
            try:
                component_func = globals()[component_name]
                scores[component_name] = component_func()
                print(f"PASS: {component_name}")
            except Exception as e:
                scores[component_name] = 0.0
                print(f"FAIL: {component_name}: {e}")
    
        all_passed = all(scores.get(key, 0) == 1.0 for key in WEIGHTS)
        final_score = 1.0 if all_passed else 0.0
    
        Path("$PROJECT/external/public-verifiers/dbt-fix-refund-reconciliation/refund-verified-02-logs").mkdir(parents=True, exist_ok=True)
        Path("$PROJECT/external/public-verifiers/dbt-fix-refund-reconciliation/refund-verified-02-logs/reward.txt").write_text(str(final_score))
        # Harbor requires reward.json to be a single-key dict[str, float|int]
        # (harbor.utils.pass_at_k rejects len(rewards) != 1; VerifierResult.rewards
        # is dict[str, float|int]). Emit the overall score as {"reward": ...},
        # matching reward.txt; per-component pass/fail is in the verifier stdout above.
        Path("$PROJECT/external/public-verifiers/dbt-fix-refund-reconciliation/refund-verified-02-logs/reward.json").write_text(json.dumps({"reward": final_score}))
    
        print(f"\nFinal Score: {final_score}")
>       assert final_score == 1.0, f"Score: {final_score}"
E       AssertionError: Score: 0.0
E       assert 0.0 == 1.0

test_outputs_native.py:672: AssertionError
=========================== short test summary info ===========================
FAILED test_outputs_native.py::test_solution - AssertionError: Score: 0.0
1 failed in 44.92s

```

### dbt-fix-division-by-zero

原始 pytest 输出（只进行路径重映射，未改测试断言）：

```text
CMD: dbt deps
STDOUT: [0m12:36:59  Running with dbt=1.12.6
[0m12:37:02  Installing dbt-labs/dbt_utils
[0m12:37:05  Installed from version 1.3.3
[0m12:37:05  Updated version available: 1.4.1
[0m12:37:05  
[0m12:37:05  Updates available for packages: ['dbt-labs/dbt_utils']                 
Update your versions in packages.yml, then run dbt deps

CMD: dbt run -s rpt_customer_metrics
STDOUT: [0m12:37:12  Running with dbt=1.12.6
[0m12:37:12  Registered adapter: duckdb=1.11.0
[0m12:37:17  [[33mWARNING[0m]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 10 unused configuration paths:
- models.retail_warehouse.intermediate
- models.retail_warehouse.staging.sfdc
- models.retail_warehouse.staging.ga
- models.retail_warehouse.staging.pos
- models.retail_warehouse.staging
- models.retail_warehouse.staging.sap
- models.retail_warehouse.staging.payments
- models.retail_warehouse.marts
- models.retail_warehouse.staging.legacy
- models.retail_warehouse.staging.wms
[0m12:37:19  Found 2333 models, 7 snapshots, 60 analyses, 10 seeds, 814 data tests, 1348 sources, 667 macros
[0m12:37:19  
[0m12:37:19  Concurrency: 4 threads (target='dev')
[0m12:37:19  
[0m12:37:21  1 of 1 START sql table model main.rpt_customer_metrics ......................... [RUN]
[0m12:37:21  1 of 1 OK created sql table model main.rpt_customer_metrics .................... [[32mOK[0m in 0.22s]
[0m12:37:21  
[0m12:37:21  Finished running 1 table model in 0 hours 0 minutes and 1.77 seconds (1.77s).
[0m12:37:23  
[0m12:37:23  [32mCompleted successfully[0m
[0m12:37:23  
[0m12:37:23  Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=1

PASS: component_1_model_compiles
FAIL: component_2_no_inf_nan_values: Found 766 inf/nan values
FAIL: component_3_row_count: Row count mismatch: 383 vs 382
FAIL: component_4_ltv_tier_exists: Binder Error: Referenced column "ltv_tier" not found in FROM clause!
Candidate bindings: "total_orders", "total_revenue", "revenue_velocity_ratio", "last_order_date", "customer_id"

LINE 2:             SELECT ltv_tier FROM main.rpt_customer_metrics LIMIT 1
                           ^
FAIL: component_5_ltv_tier_valid_values: Binder Error: Referenced column "ltv_tier" not found in FROM clause!
Candidate bindings: "total_orders", "total_revenue", "revenue_velocity_ratio", "last_order_date", "customer_id"

LINE 2:             SELECT DISTINCT ltv_tier FROM main.rpt_customer_metrics
                                    ^
FAIL: component_6_uses_window_function: Must use PERCENT_RANK() or NTILE() window function for tier calculation
FAIL: component_7_tier_distribution: Binder Error: Referenced column "ltv_tier" not found in FROM clause!
Candidate bindings: "total_orders", "total_revenue", "revenue_velocity_ratio", "last_order_date", "customer_id"

LINE 4:             GROUP BY ltv_tier
                             ^
FAIL: component_8_new_columns_exist: Missing columns: ['days_since_last_order', 'orders_last_180d', 'customer_engagement_score', 'churn_risk_score', 'customer_value_rank', 'customer_value_percentile', 'above_median_revenue']
FAIL: component_9_engagement_score_formula: Binder Error: Referenced column "days_since_last_order" not found in FROM clause!
Candidate bindings: "first_order_date", "last_order_date", "orders_last_30d", "orders_last_90d", "revenue_velocity_ratio"

LINE 4:                 days_since_last_order,
                        ^
FAIL: component_10_churn_risk_score_formula: Binder Error: Referenced column "days_since_last_order" not found in FROM clause!
Candidate bindings: "first_order_date", "last_order_date", "orders_last_30d", "orders_last_90d", "revenue_velocity_ratio"

LINE 4:                 days_since_last_order,
                        ^
FAIL: component_11_engagement_score_bounds: Binder Error: Referenced column "customer_engagement_score" not found in FROM clause!
Candidate bindings: "customer_id", "total_revenue", "revenue_velocity_ratio", "order_frequency_trend", "orders_per_month"

LINE 2:             SELECT MIN(customer_engagement_score), MAX(customer_engagement_score)
                               ^
FAIL: component_12_churn_risk_score_bounds: Binder Error: Referenced column "churn_risk_score" not found in FROM clause!
Candidate bindings: "first_order_date", "revenue_velocity_ratio", "orders_per_month", "customer_id", "revenue_last_30d"

LINE 2:             SELECT MIN(churn_risk_score), MAX(churn_risk_score)
                               ^
FAIL: component_13_customer_value_rank: Binder Error: Referenced column "customer_value_rank" not found in FROM clause!
Candidate bindings: "customer_id", "total_revenue", "revenue_last_30d", "revenue_last_90d", "last_order_date"

LINE 3:             WHERE customer_value_rank = 1
                          ^
FAIL: component_14_above_median_revenue: Binder Error: Referenced column "above_median_revenue" not found in FROM clause!
Candidate bindings: "avg_order_value", "revenue_velocity_ratio", "revenue_last_30d", "revenue_last_90d", "total_revenue"

LINE 2:             SELECT customer_id, total_revenue, above_median_revenue
                                                       ^
FAIL: component_15_ltv_tier_waterfall_logic: Binder Error: Referenced column "orders_last_180d" not found in FROM clause!
Candidate bindings: "orders_last_30d", "orders_last_90d", "last_order_date", "revenue_last_30d", "revenue_last_90d"

LINE 6:                 orders_last_180d,
                        ^

Final Score: 0.0
F
================================== FAILURES ===================================
________________________________ test_solution ________________________________

    def test_solution():
        """Run all component tests and compute final score."""
        scores = {}
    
        for component_name in WEIGHTS:
            try:
                component_func = globals()[component_name]
                scores[component_name] = component_func()
                print(f"PASS: {component_name}")
            except Exception as e:
                scores[component_name] = 0.0
                print(f"FAIL: {component_name}: {e}")
    
        all_passed = all(scores.get(key, 0) == 1.0 for key in WEIGHTS)
        final_score = 1.0 if all_passed else 0.0
    
        Path("$PROJECT/external/public-verifiers/dbt-fix-division-by-zero/division-verified-01-logs").mkdir(parents=True, exist_ok=True)
        Path("$PROJECT/external/public-verifiers/dbt-fix-division-by-zero/division-verified-01-logs/reward.txt").write_text(str(final_score))
        # Harbor requires reward.json to be a single-key dict[str, float|int]
        # (harbor.utils.pass_at_k rejects len(rewards) != 1; VerifierResult.rewards
        # is dict[str, float|int]). Emit the overall score as {"reward": ...},
        # matching reward.txt; per-component pass/fail is in the verifier stdout above.
        Path("$PROJECT/external/public-verifiers/dbt-fix-division-by-zero/division-verified-01-logs/reward.json").write_text(json.dumps({"reward": final_score}))
    
        print(f"\nFinal Score: {final_score}")
>       assert final_score == 1.0, f"Score: {final_score}"
E       AssertionError: Score: 0.0
E       assert 0.0 == 1.0

test_outputs_native.py:645: AssertionError
=========================== short test summary info ===========================
FAILED test_outputs_native.py::test_solution - AssertionError: Score: 0.0
1 failed in 40.37s

```

# DataPatch v2：同题公开开发集重测（非官方成绩）

数据集：snowflake-data-eng-bench/native-public-development-subset

Snowflake-Labs/data-eng-bench 固定公开开发题；原始数据、dbt项目和任务说明，Windows native路径适配；非官方Docker/Harbor成绩，非未知保留集。

状态：completed；记录 2/2 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 0/2 | 0.0% | 未做重复实验 | 166.03 | 533419 | 0.168127 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| dbt-fix-refund-reconciliation | verified | 0 | False | refund-v2-01-verified |
| dbt-fix-division-by-zero | verified | 0 | False | division-v2-01-verified |

## 外部任务验收与限制

固定 commit：`a3278ad102829a6084dde086244a0ef665a8011c`；模型：`deepseek-flash`。

| 任务 | 最大步数 | 停止原因 | 上游组件通过/总数 | 二元reward |
|---|---:|---|---:|---:|
| dbt-fix-refund-reconciliation | 24 | step_limit | 12/13 | 0.0 |
| dbt-fix-division-by-zero | 16 | step_limit | 14/15 | 0.0 |

- Only 2 public development trial(s), one per task; no performance/generalization claim.
- Native Windows/dbt versions and selected-ancestor initialization differ from the official Linux Docker environment.
- Task success requires every upstream component to pass; partial component credit is descriptive only.
- No React comparison was run; these are development executions rather than an ablation experiment.
- At least one execution reached the model step limit; inspect per-trial action logs before claiming completed delivery.

### dbt-fix-refund-reconciliation

原始 pytest 输出（只进行路径重映射，未改测试断言）：

```text
CMD: dbt deps
STDOUT: [0m12:47:47  Running with dbt=1.12.6
[0m12:47:50  Installing dbt-labs/dbt_utils
[0m12:47:53  Installed from version 1.3.3
[0m12:47:53  Updated version available: 1.4.1
[0m12:47:53  
[0m12:47:53  Updates available for packages: ['dbt-labs/dbt_utils']                 
Update your versions in packages.yml, then run dbt deps

CMD: dbt run -s rpt_return_reconciliation
STDOUT: [0m12:48:01  Running with dbt=1.12.6
[0m12:48:01  Registered adapter: duckdb=1.11.0
[0m12:48:05  [[33mWARNING[0m]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 10 unused configuration paths:
- models.retail_warehouse.staging.legacy
- models.retail_warehouse.staging
- models.retail_warehouse.staging.ga
- models.retail_warehouse.staging.pos
- models.retail_warehouse.intermediate
- models.retail_warehouse.marts
- models.retail_warehouse.staging.payments
- models.retail_warehouse.staging.sap
- models.retail_warehouse.staging.wms
- models.retail_warehouse.staging.sfdc
[0m12:48:07  Found 2333 models, 7 snapshots, 60 analyses, 10 seeds, 814 data tests, 1348 sources, 667 macros
[0m12:48:08  
[0m12:48:08  Concurrency: 4 threads (target='dev')
[0m12:48:08  
[0m12:48:09  1 of 1 START sql table model main.rpt_return_reconciliation .................... [RUN]
[0m12:48:09  1 of 1 OK created sql table model main.rpt_return_reconciliation ............... [[32mOK[0m in 0.23s]
[0m12:48:09  
[0m12:48:09  Finished running 1 table model in 0 hours 0 minutes and 1.96 seconds (1.96s).
[0m12:48:11  
[0m12:48:11  [32mCompleted successfully[0m
[0m12:48:11  
[0m12:48:11  Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=1

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
    
        Path("$PROJECT/external/public-verifiers/dbt-fix-refund-reconciliation/refund-v2-01-logs").mkdir(parents=True, exist_ok=True)
        Path("$PROJECT/external/public-verifiers/dbt-fix-refund-reconciliation/refund-v2-01-logs/reward.txt").write_text(str(final_score))
        # Harbor requires reward.json to be a single-key dict[str, float|int]
        # (harbor.utils.pass_at_k rejects len(rewards) != 1; VerifierResult.rewards
        # is dict[str, float|int]). Emit the overall score as {"reward": ...},
        # matching reward.txt; per-component pass/fail is in the verifier stdout above.
        Path("$PROJECT/external/public-verifiers/dbt-fix-refund-reconciliation/refund-v2-01-logs/reward.json").write_text(json.dumps({"reward": final_score}))
    
        print(f"\nFinal Score: {final_score}")
>       assert final_score == 1.0, f"Score: {final_score}"
E       AssertionError: Score: 0.0
E       assert 0.0 == 1.0

test_outputs_native.py:672: AssertionError
=========================== short test summary info ===========================
FAILED test_outputs_native.py::test_solution - AssertionError: Score: 0.0
1 failed in 39.32s

```

### dbt-fix-division-by-zero

原始 pytest 输出（只进行路径重映射，未改测试断言）：

```text
CMD: dbt deps
STDOUT: [0m12:46:49  Running with dbt=1.12.6
[0m12:46:53  Installing dbt-labs/dbt_utils
[0m12:46:57  Installed from version 1.3.3
[0m12:46:57  Updated version available: 1.4.1
[0m12:46:57  
[0m12:46:57  Updates available for packages: ['dbt-labs/dbt_utils']                 
Update your versions in packages.yml, then run dbt deps

CMD: dbt run -s rpt_customer_metrics
STDOUT: [0m12:47:05  Running with dbt=1.12.6
[0m12:47:05  Registered adapter: duckdb=1.11.0
[0m12:47:09  [[33mWARNING[0m]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 10 unused configuration paths:
- models.retail_warehouse.staging.sap
- models.retail_warehouse.staging.payments
- models.retail_warehouse.staging.wms
- models.retail_warehouse.staging.pos
- models.retail_warehouse.staging.ga
- models.retail_warehouse.marts
- models.retail_warehouse.staging
- models.retail_warehouse.staging.sfdc
- models.retail_warehouse.intermediate
- models.retail_warehouse.staging.legacy
[0m12:47:11  Found 2333 models, 7 snapshots, 60 analyses, 10 seeds, 814 data tests, 1348 sources, 667 macros
[0m12:47:11  
[0m12:47:11  Concurrency: 4 threads (target='dev')
[0m12:47:11  
[0m12:47:13  1 of 1 START sql table model main.rpt_customer_metrics ......................... [RUN]
[0m12:47:13  1 of 1 OK created sql table model main.rpt_customer_metrics .................... [[32mOK[0m in 0.27s]
[0m12:47:13  
[0m12:47:13  Finished running 1 table model in 0 hours 0 minutes and 1.96 seconds (1.96s).
[0m12:47:15  
[0m12:47:15  [32mCompleted successfully[0m
[0m12:47:15  
[0m12:47:15  Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=1

PASS: component_1_model_compiles
PASS: component_2_no_inf_nan_values
FAIL: component_3_row_count: Row count mismatch: 380 vs 382
PASS: component_4_ltv_tier_exists
PASS: component_5_ltv_tier_valid_values
PASS: component_6_uses_window_function
PASS: component_7_tier_distribution
PASS: component_8_new_columns_exist
PASS: component_9_engagement_score_formula
PASS: component_10_churn_risk_score_formula
PASS: component_11_engagement_score_bounds
PASS: component_12_churn_risk_score_bounds
PASS: component_13_customer_value_rank
PASS: component_14_above_median_revenue
PASS: component_15_ltv_tier_waterfall_logic

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
    
        Path("$PROJECT/external/public-verifiers/dbt-fix-division-by-zero/division-v2-01-logs").mkdir(parents=True, exist_ok=True)
        Path("$PROJECT/external/public-verifiers/dbt-fix-division-by-zero/division-v2-01-logs/reward.txt").write_text(str(final_score))
        # Harbor requires reward.json to be a single-key dict[str, float|int]
        # (harbor.utils.pass_at_k rejects len(rewards) != 1; VerifierResult.rewards
        # is dict[str, float|int]). Emit the overall score as {"reward": ...},
        # matching reward.txt; per-component pass/fail is in the verifier stdout above.
        Path("$PROJECT/external/public-verifiers/dbt-fix-division-by-zero/division-v2-01-logs/reward.json").write_text(json.dumps({"reward": final_score}))
    
        print(f"\nFinal Score: {final_score}")
>       assert final_score == 1.0, f"Score: {final_score}"
E       AssertionError: Score: 0.0
E       assert 0.0 == 1.0

test_outputs_native.py:645: AssertionError
=========================== short test summary info ===========================
FAILED test_outputs_native.py::test_solution - AssertionError: Score: 0.0
1 failed in 42.24s

```

## 与v1的描述性比较

同题公开开发集重测；每题步数保持24/16，两轮均没有触发费用上限。总Tokens从1,672,068下降到533,419（减少68.1%），估算费用从0.509549下降到0.168127 USD（减少67.0%）。任务通过仍为0/2，不能将组件通过增加写成任务成功率提高。

退款题仍在排名总体包含NULL；客户指标题擅自改变状态大小写过滤语义，导致少2个客户。两题都step_limit，提醒分别触发一次但没有保证最终交付。以上为验收后的人工分析，没有回传模型重试。

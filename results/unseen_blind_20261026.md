# DataPatch 未研究公开任务：单次无人工辅助试跑

数据集：snowflake-data-eng-bench/native-public-development-subset

Snowflake-Labs/data-eng-bench 固定公开开发题；原始数据、dbt项目和任务说明，Windows native路径适配；非官方Docker/Harbor成绩，非未知保留集。

在既有公共项目中，按路径元数据从两个适配候选中固定种子单次抽取此前未研究的任务。仅提供原工单、项目与数据，未加入人工业务契约或答案；Agent停止后才下载原测试。Windows/DuckDB本地适配，非官方Harbor成绩；无法保证模型预训练未见过该公开题。

状态：completed；记录 1/1 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 1/1 | 100.0% | 未做重复实验 | 139.08 | 127925 | 0.056202 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| dbt-carrier-delivery-performance | verified | 0 | True | unseen-carrier-20261026-001-verified |

## 外部任务验收与限制

固定 commit：`a3278ad102829a6084dde086244a0ef665a8011c`；模型：`deepseek-flash`。

| 任务 | 最大步数 | 停止原因 | 上游组件通过/总数 | 二元reward |
|---|---:|---|---:|---:|
| dbt-carrier-delivery-performance | 10 | cost_limit | 16/16 components | 1.0 |

- Only 1 public development trial(s) in a fixed task subset; no performance/generalization claim.
- Native Windows/dbt versions and selected-ancestor initialization differ from the official Linux Docker environment.
- Task success requires every upstream component to pass; partial component credit is descriptive only.
- No React comparison was run; these are development executions rather than an ablation experiment.

### dbt-carrier-delivery-performance

原始 pytest 输出（只进行路径重映射，未改测试断言）：

```text
CMD: dbt deps
STDOUT: 09:38:23  Running with dbt=1.12.6
09:38:23  Installing ../dbt_packages/dbt_utils
09:38:24  Installed from <local @ ../dbt_packages/dbt_utils>

CMD: dbt run -s rpt_carrier_performance
STDOUT: 09:38:31  Running with dbt=1.12.6
09:38:31  Registered adapter: duckdb=1.11.0
09:38:35  [WARNING]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 10 unused configuration paths:
- models.retail_warehouse.staging.sap
- models.retail_warehouse.staging.ga
- models.retail_warehouse.staging.wms
- models.retail_warehouse.intermediate
- models.retail_warehouse.staging
- models.retail_warehouse.staging.pos
- models.retail_warehouse.staging.payments
- models.retail_warehouse.staging.legacy
- models.retail_warehouse.marts
- models.retail_warehouse.staging.sfdc
09:38:37  Found 2332 models, 7 snapshots, 60 analyses, 10 seeds, 814 data tests, 1348 sources, 667 macros
09:38:37
09:38:37  Concurrency: 4 threads (target='dev')
09:38:37
09:38:38  1 of 1 START sql view model main.rpt_carrier_performance ....................... [RUN]
09:38:38  1 of 1 OK created sql view model main.rpt_carrier_performance .................. [OK in 0.18s]
09:38:38
09:38:38  Finished running 1 view model in 0 hours 0 minutes and 1.77 seconds (1.77s).
09:38:40
09:38:40  Completed successfully
09:38:40
09:38:40  Done. PASS=1 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=1

PASS: component_1_model_compiles
PASS: component_2_no_inf_nan_values
PASS: component_3_row_count
PASS: component_4_required_columns
PASS: component_5_valid_tier_values
PASS: component_6_speed_percentile_validation
PASS: component_7_cost_percentile_validation
PASS: component_8_waterfall_tier_logic
PASS: component_9_cost_tier_logic
PASS: component_10_peer_rank_validation
PASS: component_11_peer_speed_percentile_validation
PASS: component_12_above_peer_avg_validation
PASS: component_13_efficiency_index_bounds
PASS: component_14_efficiency_index_formula
PASS: component_15_reliability_index_bounds
PASS: component_16_reliability_index_formula

Final Score: 1.0
.
1 passed in 34.67s

```

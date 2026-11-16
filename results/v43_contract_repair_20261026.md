# data-eng-bench 公开开发任务：本地适配实际结果（非官方成绩）

数据集：snowflake-data-eng-bench/native-public-development-subset

Snowflake-Labs/data-eng-bench 固定公开开发题；原始数据、dbt项目和任务说明，Windows native路径适配；非官方Docker/Harbor成绩，非未知保留集。

状态：completed；记录 1/1 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 1/1 | 100.0% | 未做重复实验 | 37.09 | 62455 | 0.021761 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| dbt-fix-product-metrics | verified | 0 | True | product-guided-v43-20261026-verified |

## 外部任务验收与限制

固定 commit：`a3278ad102829a6084dde086244a0ef665a8011c`；模型：`deepseek-flash`。

| 任务 | 最大步数 | 停止原因 | 上游组件通过/总数 | 二元reward |
|---|---:|---|---:|---:|
| dbt-fix-product-metrics | 4 | step_limit | 11 passed / 0 failed tests | 1.0 |

- Only 1 public development trial(s) in a fixed task subset; no performance/generalization claim.
- Native Windows/dbt versions and selected-ancestor initialization differ from the official Linux Docker environment.
- Task success requires every upstream component to pass; partial component credit is descriptive only.
- No React comparison was run; these are development executions rather than an ablation experiment.
- Explicit project-provided public business contracts assisted this execution; this is not an unassisted original-ticket or official benchmark result. Target starting hashes identify any preloaded repair continuation.
- At least one execution reached the model step limit; inspect per-trial action logs before claiming completed delivery.

### dbt-fix-product-metrics

原始 pytest 输出（只进行路径重映射，未改测试断言）：

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.1.1, pluggy-1.7.0 -- $PROJECT\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: $PROJECT
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 11 items

test_outputs_product_guided_v43_20261026.py::test_product_revenue_matches_order_lines PASSED [  9%]
test_outputs_product_guided_v43_20261026.py::test_data_quality_check_2 PASSED [ 18%]
test_outputs_product_guided_v43_20261026.py::test_units_sold_accuracy PASSED [ 27%]
test_outputs_product_guided_v43_20261026.py::test_order_count_accuracy PASSED [ 36%]
test_outputs_product_guided_v43_20261026.py::test_model_structure_preserved PASSED [ 45%]
test_outputs_product_guided_v43_20261026.py::test_variant_counts_match PASSED [ 54%]
test_outputs_product_guided_v43_20261026.py::test_no_negative_values PASSED [ 63%]
test_outputs_product_guided_v43_20261026.py::test_all_products_present PASSED [ 72%]
test_outputs_product_guided_v43_20261026.py::test_no_cancelled_orders_included PASSED [ 81%]
test_outputs_product_guided_v43_20261026.py::test_product_count_matches_source PASSED [ 90%]
test_outputs_product_guided_v43_20261026.py::test_avg_unit_price_formula PASSED [100%]

============================= 11 passed in 1.19s ==============================

```

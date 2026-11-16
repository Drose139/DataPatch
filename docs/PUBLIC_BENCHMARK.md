# 外部公开任务：data-eng-bench

DataPatch 的外部验证使用 [Snowflake-Labs/data-eng-bench](https://github.com/Snowflake-Labs/data-eng-bench) 的公开任务。本地适配固定在 commit `a3278ad102829a6084dde086244a0ef665a8011c`，当前支持八题，原四题如下；新增时区、连续日报、结算日汇率、cohort留存及边界见 [八题说明](PUBLIC_EIGHT_TASKS.md)：

| 任务 | 目标模型路径 | 任务类型 | 上游评分协议 |
|---|---|---|---|
| `dbt-fix-refund-reconciliation` | `models/marts/sales/rpt_return_reconciliation.sql` | 退款对账修复 | 组件结果与二元 `reward.json` |
| `dbt-fix-division-by-zero` | `models/marts/customer/rpt_customer_metrics.sql` | 客户指标修复 | 组件结果与二元 `reward.json` |
| `dbt-fix-inventory-model` | `models/marts/inventory/rpt_product_inventory_metrics.sql` | 库存指标修复 | 组件结果与二元 `reward.json` |
| `dbt-fix-product-metrics` | `models/marts/product/fct_product_metrics.sql` | 创建商品汇总模型 | 普通 pytest 与原 `test.sh` 退出码/计数规则 |

四题都是**固定公开开发案例**，用于核实独立来源的真实 dbt 项目上的执行能力，不能代表全量 103 题效果或未知任务泛化。历史两题协议保持原范围；新增任务不会把旧报告的分母扩大到四题。选题依据与登记见 [PUBLIC_EXPANSION.md](PUBLIC_EXPANSION.md)，当前模型参数和预算见 [PUBLIC_RUNTIME.md](PUBLIC_RUNTIME.md)。

原Flash两轮已封存，后续商品契约辅助修复与零API八题成品验收分别保存。最新实际成绩统一查阅 [RESULTS.md](RESULTS.md) 及其链接的原始报告；本页下方的 0/2 属于明确标记的历史版本。

## 下载与来源记录

```powershell
& '.venv/Scripts/python.exe' 'scripts/fetch_public_benchmark.py' '--task' 'dbt-fix-refund-reconciliation' '--task' 'dbt-fix-division-by-zero' '--task' 'dbt-fix-inventory-model' '--task' 'dbt-fix-product-metrics'
```

脚本从固定 commit 流式读取上游压缩归档，只提取 DuckDB dbt 项目、原始数据库指针、运行时数据修正脚本、许可证和选定任务的初始输入。`solution/` 和任务 `tests/` 不提取、不保存；归档本身不落盘。dbt 项目自带的通用可见测试属于原运行环境，会保留。

原始 `retail.duckdb` 为 488,910,848 字节，通过 Git LFS 对象 SHA-256 检查。所有提取文件的 SHA-256、大小、commit、任务名单写入 `external/data-eng-bench/snapshot-lock.json`。`external/` 不进入 Git。`--metadata-only` 可以跳过大数据库下载。

fetch 支持八题的显式子集；省略 `--task` 仍只选择历史两题。已存在的数据库通过相同 hash 校验后复用。

该数据库固定 SHA-256：`bd2bb1b3a7cf62aa94c191527aa30db5bf415aea97db718a1e0c11c59fc2ec2d`。

## 本地适配运行

本机只读环境检查未发现 `docker` 命令或 Docker Desktop 标准安装路径；WSL 命令存在，但没有列出可用发行版。未安装或启动系统服务。因此当前支持 **native adapted** 路径，执行受信任公开 dbt 项目；它不提供操作系统沙箱隔离。

当前统一使用 `scripts/run_public_suite.py` 顺序执行一轮。先准备好上述固定输入和冻结源码 zip，再指定已授权轮次：

```powershell
& '.venv/Scripts/python.exe' 'scripts/run_public_suite.py' '--round' '1' '--source-snapshot' 'artifacts/evaluations/v41_flash_round1_20261025_source.zip'
```

runner 仅允许 **`deepseek-flash`、thinking enabled、high、8192 输出上限**，逐任务核验模型、参数与计价配置。每题最多 **12 次模型调用**（包含复核）、估算上限 **$0.125**；四题每轮上限 **$0.50**，最多显式执行两轮，合计上限 **$1.00**。不做多模式对照。第二轮不会自动启动，已有轮次协议、case 或结果也不会被覆盖。输入/输出的发送前预算预留与实际扣费口径见 [运行配置](PUBLIC_RUNTIME.md)。

运行前先写 `artifacts/protocols/v41_flash_round1_20261025.json`，然后逐题执行 prepare → run → 独立 pytest → report。结果写入 `artifacts/evaluations/v41_flash_round1_20261025.json` 和同名 Markdown。`--task` 可重复指定显式子集，其预算和分母按所选任务固定；省略时是表中的四题。失败记录与原验收反馈照样保留，不据此回传同次 solver 重试。

每题使用全新的文件和数据库。三个修复任务复制基础项目，运行原 `fix_data.py`、`dbt deps`，预建目标及祖先后覆盖原始 buggy SQL。商品创建任务只预建四个声明的 staging 输入及祖先，目标 SQL 保持缺失，由 Agent 创建。当前交付 build 只选择目标模型，并核验 manifest/run results 中确有该目标的成功节点；零节点的 dbt 退出码 0 不算成功。历史版本的 build 原始证据不追改。

`run` 调用项目自己的 `Workspace` 与 `Agent`。事件、模型名、预算、运行结果和 patch 保存至 `external/native-results/`，不进入 Agent 的文件工具根目录。Agent 只能访问 case 下的业务输入，没有最终 verifier 或参考解法。

## 最终验收

runner 只在本题 Agent 停止后调用独立评估器。需要单独验收一个已停止的案例时使用：

```powershell
& '.venv/Scripts/python.exe' 'integrations/harbor_agent.py' 'evaluate' '--case' 'external/native-cases/refund-v41-flash-r1'
```

此时才下载原任务 `tests/test_outputs.py` 到 case 外的 `external/public-verifiers/`。只将 `/app/` 项目、数据库及 `/logs/verifier` 路径重映射，保存原始与适配文件的 SHA-256。测试断言保持原样，反馈不返回同次 Agent。

- 前三题记录 `grading_protocol=component_reward_json`，用实际 pytest 执行取得原组件结果与二元 reward；组件部分通过不等于整题通过。
- 商品汇总题记录 `grading_protocol=pytest_exit_status`。独立保存 pinned 原 `test.sh` 及 hash，按其规则判定：pytest 退出码 0、至少一个通过测试，并且无失败、错误或跳过。报告保留 `pytest_counts`、原 stdout、评分来源与 hash；不伪造组件标签。

最终通过还要求模型执行完成和目标模型的独立最终 build 成功。**直接 `python test_outputs.py` 只定义函数，不能构成有效验收；退出码 0 本身也不等于任务通过。**

若后续根据公开验收结果修改通用策略，再运行仍属于公开开发迭代。当前四题也不作为未知保留集；最多两轮的限制保持不变。

## 与官方设置的差异

| 项目 | 当前本地路径 | 官方 Harbor 路径 |
|---|---|---|
| 环境 | Windows 本地 Python/dbt，记录实际版本 | Linux Docker，官方基础镜像及依赖 |
| 初始化 | 修复题预建目标及祖先；创建题只预建声明输入 | 基础镜像中全项目 `dbt run` |
| 文件路径 | `/app/` 路径重映射 | 原路径 |
| Agent | DataPatch 有边界的文件/SQL/dbt工具 | 通过 Harbor agent integration |
| 验收 | 原始断言，路径适配，Agent结束后单独执行 | Harbor 注入原始 verifier |
| 结果名称 | 固定公开开发子集、本地适配结果 | 官方对应后端全量/声明子集结果 |

**本地结果不能标为官方 Harbor 榜单成绩。** 上游全量榜至少要求每题三次独立试验；平均单次成功率与三次全部成功的一致性分开报告。上游 README 还指出 `dbt-fix-timezone-sales` 的 DuckDB 验收可能受执行顺序影响，这也是后续扩大集合时必须单独说明的问题。

标准运行以[上游 README](https://github.com/Snowflake-Labs/data-eng-bench/blob/master/README.md) 为准；[Harbor 文档](https://docs.harborframework.com/agents/pre-integrated-agents)提供通用 Agent 和自定义 Agent 的正式入口。本项目尚未宣称完成 Docker/Harbor 全量跑分。

## v1 历史两题：0/2

以下为 `public_native_subset_20261025` 的 v1 历史记录，不是当前四题 Flash thinking 运行。模型均为当时的 `deepseek-flash`，每题独立原始工作目录、各一次，不向同次 Agent 回传验收反馈：

| 任务 | 最大步数 | 原验收组件通过 | 任务二元reward | 模型调用 | 停止原因 | 估算USD |
|---|---:|---:|---:|---:|---|---:|
| refund-reconciliation | 24 | 12/13 | 0 | 24 | step_limit | 0.301547 |
| division-by-zero | 16 | 1/15 | 0 | 16 | step_limit | 0.208002 |

**任务通过 0/2**；共 40 次模型调用、66 次工具调用、1,672,068 Tokens，配置单价估算总费用 0.509549 USD。两题最大步数不同，属于开发实测记录；没有进行模式对照或重复运行，不据此作泛化或显著性结论。

首次退款对账任务运行中，DeepSeek 已产生补丁，模型能够编译执行；上游 13 个组件通过 12 个，但 `component_8_waterfall_tier_logic` 失败，所以整个任务二元 reward 为 0。Agent 还重复执行同一条已经成功返回的查询，直至 24 步上限，未完成最终自然语言交付。

验收结束后的人工分析发现：SQL 写成 `CASE WHEN total_processing_days IS NOT NULL THEN PERCENT_RANK() OVER (...) END`，仅把 NULL 行的最终结果置空，NULL 行仍进入窗口总体；任务要求分位数只在非 NULL 记录中计算。因此窗口分母错误，若干记录的退款分层错误。编译通过、无 inf/NaN 和正确列结构，都不能代替这项业务语义检查。

这个原因没有反馈给同一 Agent 继续重跑，也没有把失败补丁手工改成成功记录。该历史版本存在重复工具调用和预算耗尽问题；后续版本加入的通用改进不改变这一版的失败判定。原始上游反馈和模型成本见 `artifacts/evaluations/public_native_subset_20261025.json`。

第二题在 16 步内一直探索和查询数据，没有产生模型文件修改。最终验收只通过编译组件；目标新增列缺失以及原始数据问题仍在，其余 14 个组件失败。这是预算内没有从探索推进到交付的失败，不能描述为已经实现了客户指标修复。

## v2 历史两题同题重测：0/2

v2 改为目标模型及相关依赖的聚焦上下文，并加入连续读取、相同结果和剩余调用预算的通用进度提醒。没有向模型提供原验收代码、反例或参考补丁。两题使用全新原始工作目录，保留 v1 各题的步数上限；本次每 run 费用上限为 0.25 USD，两次均未触发。

| 任务 | 原验收组件通过 | 任务二元reward | 调用/工具数 | Tokens | 估算USD |
|---|---:|---:|---:|---:|---:|
| refund-reconciliation | 12/13 | 0 | 24/31 | 300731 | 0.093669 |
| division-by-zero | 14/15 | 0 | 16/20 | 232688 | 0.074458 |

v2 **任务通过仍为 0/2**。总 Tokens 减少 68.1%、估算费用减少 67.0%，但不能写成任务成功率提高。两次仍到达步数上限，分别触发一次停滞提醒；客户指标题已能在预算内生成和执行补丁。

验收后的人工分析发现：退款题的 `NULLS LAST` 仍未排除 NULL 行参与排名总体；客户指标题把原有 `status != 'CANCELLED'` 变成 `upper(status) <> 'CANCELLED'`，擅自改变大小写过滤语义，导致少 2 位客户。聚焦上下文和提醒解决了部分执行效率问题，还需要更可靠的业务契约核对与保留既有语义。

完整原验收输出见 `artifacts/evaluations/public_native_v2_20261025.json` 和同名 `.md`。运行前冻结的源码为 `public_native_v2_20261025_source.zip`，core SHA-256 为 `7fb8fb2152886b376b5b6a16f962c244eb1033228a2ec3f8f69d2a2d1949cde7`。这是同题公开开发集重测，不能称为盲测、保留集或未知任务泛化结果。

后续 v3（`public_native_v3_20261025`）与 v3.1（`public_native_v31_20261025`）也是两题公开开发重测，最终均为 0/2。历史 v4 Pro 四题因 HTTP402 余额不足中断，保留四条未完成记录，不能当作完整模型正确率实验。各版原始证据与当前 Flash 轮次的最终结果统一见 [RESULTS.md](RESULTS.md)；当前支持四题不等于已通过四题。

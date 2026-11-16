# DataPatch：公开工程读码与面试指南

公开工程这条路径处理真实 dbt 项目：给 Agent 一张数据工程工单，让它找到输入、修改或创建 SQL 模型、构建并检查结果，最后由独立程序验收。当前固定四题覆盖退款、客户、库存和新建产品指标。准确成绩与版本见 [RESULTS.md](RESULTS.md)，运行设置见 [PUBLIC_RUNTIME.md](PUBLIC_RUNTIME.md)。

dbt 把带有依赖声明的 SQL 文件编译、执行为数据库中的表或视图；DuckDB 是本机实际计算和保存这些表的数据库。模型既指 SQL 文件，也指它定义的输出关系，阅读时要区分源文件路径与数据库表名。

## 沿一次任务看完整路径

入口在 `integrations/harbor_agent.py`，公开任务使用这条独立路径，不经过网页创建合成任务的 `RunService`。

```text
prepare_native_case：固定上游版本 → 独立 case → 公开说明/项目/数据库 → 准备上游模型
run_native_case：Workspace → 聚焦上下文 → Agent ↔ 工具 → 最终目标构建 → 保存事件与补丁
evaluate_native_case：Agent 已停止 → case 外的原始 pytest 验收 → 原始反馈
render_public_summary：校验执行与评分协议 → 整题结果 → 汇总报告与源码摘要
```

case 中的 `instruction.md` 是公开业务要求，`project/models/` 是可读写的 SQL 模型，`database/retail.duckdb` 是实际数据。原始运行 JSON、逐次 JSONL 和 patch 保存在 case 外的 `external/native-results/`；验收程序位于另一个目录，避免进入求解上下文。固定任务名称到输出路径的映射属于运行适配器，通用上下文的源模型选择不依赖 task ID。

模型发出 Tool Calling 消息，例如 `write_model(path, content)`；Python 解析参数、调用 `Workspace` 中的方法，将真实返回值作为下一轮工具消息交回模型。模型负责提出动作，程序负责执行、权限边界、预算和证据保存。

## 目标还不存在时，如何找到输入

新建 `fct_product_metrics` 时，寻找这个文件不会得到业务输入。`context.py::build_task_context()` 先识别公开要求中的输出名或路径；输出不存在时进入创建分支，保留 `requested_target`，指导确认输入后创建，而不是继续寻找缺失文件。

随后依次做四件事：

1. 优先从 Requirements 和明确的输入实体列表提取词，例如 products、variants、orders、order line items；词形归一使复数也能匹配文件名。
2. 根据模型名匹配相关候选，并覆盖不同输入实体。工单明确要求 staging 时优先选 staging；相关度相同时，优先 `stg_<所属目录>__<实体>` 这种与目录一致的命名空间。最多预读 6 个，每个 SQL 最多 3,500 字符。
3. 提供候选 SQL、`ref()`／`source()` 上游名，以及按相关名称筛选的真实 schema。`ref()` 指向另一个 dbt 模型，`source()` 声明外部输入表。
4. 与 README 共用 24,000 个 JSON 字符预算，记录来源、匹配词和截断情况；先裁辅助信息和候选，保留业务文档。字符预算不等于 Token 数。

首轮历史上下文选中了短名 `stg_product_variants`、`stg_order_lines`、`stg_products`、`stg_orders`。后续排序加入上述同相关度的命名空间优先规则，在产品工程中选择 `stg_product__product_variants`、`stg_orders__order_lines`、`stg_product__products`、`stg_orders__orders`。

这只是减少名称歧义的线索，不是正确性证据；已物化也不保证粒度正确。Agent 仍需用公开 SQL、schema 和查询核实关联键、去重键及过滤条件。粒度就是“一行代表什么”，例如一行订单和一行订单明细不能直接等同计数；错误地按渠道或品牌去重也会丢掉业务行。

## 构建、可见检查和独立验收分别证明什么

`dbt build` 说明被选中的模型能够编译、执行，并通过该次选择包含的 dbt 测试。适配器还检查 manifest 和 run_results，确认目标模型实际成功执行，避免“没选到模型但进程返回 0”的空成功。

业务语义需要额外证据。一个把所有均价写成 0 的模型可以运行，也没有 NaN，却不符合“收入÷销量”。`check_contracts()` 执行公开 checks SQL：返回零行表示该规则未发现反例。没有规则时返回 `available=false`；此时没有新增语义覆盖。

Agent 可用已有 `query_sql` 在物化后一次汇总多条公开约束。下面只是产品指标的局部示例，表的实际 schema 先用 `search_schema` 确认；它检查重复和加权均价，不替代人群覆盖、状态过滤等其他规则：

```sql
SELECT 'duplicate_product' AS rule, COUNT(*) AS violations
FROM (
  SELECT product_id FROM main.fct_product_metrics
  GROUP BY product_id HAVING COUNT(*) > 1
)
UNION ALL
SELECT 'weighted_unit_price', COUNT(*)
FROM main.fct_product_metrics
WHERE units_sold > 0
  AND (avg_unit_price IS NULL OR
       ABS(avg_unit_price - product_revenue / NULLIF(units_sold, 0)) > 1e-8);
```

公开要求没有规定的默认值，不能凭方便自行新增。例如这个示例只验证正销量，未替业务方决定零销量均价采用 NULL 还是 0。

Agent 结束后，`evaluate_native_case()` 才取得固定上游版本的原始 pytest，保留原文件及摘要，仅适配绝对路径。验收在 case 外执行，反馈不会追加给同一次 solver 继续修改。后续开发轮次另建案例、冻结版本和报告，保留先前失败。这里是 Windows native adapted 结果，执行环境与官方 Docker／Harbor 运行有所区别。

## 三种“测试通过”不要混在一个数字里

| 层次 | 查看什么 | 说明 |
|---|---|---|
| 本项目普通 pytest | `tests/` 的回归结果 | 检查工具、上下文、预算、报告等实现；测试替身通过不等于真实模型完成工单。fixture 测试实际执行本机 dbt，仍不调用模型。 |
| 公开任务普通 pytest 协议 | `grading_protocol=pytest_exit_status`、`pytest_counts`、退出码、reward | 产品题走此协议，按原评分规则检查实际执行数量、失败／错误／跳过等；没有 component 列表不表示没有断言。 |
| 公开任务组件协议 | `grading_protocol=component_reward_json`、components、reward | pytest 入口内部可能评估多项业务组件；查看组件失败和最终 reward，不能只看外层 pytest 的绿色提示。 |

整题成功还要求有效验收、Agent 无执行错误、最终目标构建成功及该评分协议通过。若多数组件通过但整题失败，报告同时保留两层结果；它们对应不同问题。

## 优先读懂这五处

| 顺序 | 代码 | 必须掌握／适合后续亲手修改 |
|---|---|---|
| 1 | `integrations/harbor_agent.py`：prepare、run、evaluate、summary | 能画出求解与验收的边界，指出最终通过条件；修改报告展示时从原字段取数，不重算另一套分数。 |
| 2 | `src/datapatch/agent.py`：`run()`、`_run()`、`_response()` | 能跟一次模型调用及工具返回；理解审阅占同一预算、length 停止与最后一次补丁的关系。 |
| 3 | `src/datapatch/context.py`：`_missing_target()`、`_input_entities()`、`_candidate_paths()`、`_finish()` | 能解释为什么选中四类输入；适合增加一种公开输入列表写法的支持，并验证无关源仍被排除。 |
| 4 | `src/datapatch/workspace.py`：`query_sql()`、`run_dbt()`、`check_contracts()` | 能解释只读查询、物化与违规行规则；适合为自己的合成任务补一条业务不变量，加入明确反例。 |
| 5 | `src/datapatch/provider.py`、`config.py` | 能说明消息回传、usage 和估算费用；结合 `tests/test_reasoning.py`、`tests/test_provider.py` 看离线替身验证，不用真实 API 调试每个分支。 |

一个适合个人接手的小修改：公开工单把输入写成“products; variants; orders”，为 `_input_entities()` 增加分号分隔支持。先加一个小项目测试，确认三个实体各自解析、相关源被保留、无关源被排除，再修改解析并运行 `tests/test_context.py`。这是后续练习示例，当前实现尚未加入；实验冻结期间保留当前核心版本。

另一个业务修改入口是 [代码阅读清单](CODE_READING.md) 中尚未完成的退款比例语义契约。保留自己的 Diff、反例和验证结果，面试就能展示一处实际参与的改进。

## Flash 约束与v41历史验证范围

后续仅使用 Flash，禁止 Pro；thinking high，每请求最多 8,192 输出 tokens，每任务最多 12 次成功生成请求，审阅也计入。v41原协议最多两轮，不开展多模式对照；后来用户授权继续修复后的v42/v43与零API八题验证另存，详见 [RESULTS](RESULTS.md)。金额限制和实际执行以本轮冻结配置及运行报告为准。

费用保护触发的 `BudgetExceeded` 属于预期停止，Agent 记录 `stop_reason=cost_limit`，保留已经写入的补丁并继续做最终独立构建和验收。它不冒充模型主动交付的 `model_finished`，也不自动使任务通过；最终结果仍取决于实际目标构建与原始 pytest。该停止语义用于后续版本，首轮旧预算异常记录按原样保留。

带工具的多轮请求完整回传 `reasoning_content`，日志与工作台不展示其文本；usage 中的推理输出已经包含在 completion_tokens，费用不重复计算。历史累计估算、真实缓存与未能核定的缺口见 [COSTS.md](COSTS.md)。本机 pytest、查看历史回放与报告审计都不需要模型 API。

## 约 90 秒项目介绍

> DataPatch 是一个处理 dbt 数据工程工单的 Agent 应用。输入是公开业务要求、SQL 项目和本机数据库，输出是修改补丁、执行轨迹及独立验收结果。它既能修复已有模型，也能创建新的产品指标模型。
>
> 我重点关注两个工程问题。第一是复杂项目的上下文选择：目标存在时读取目标和有限上游，目标不存在时根据公开需求选择相关 staging 输入，用统一预算保留 SQL、schema 和业务文档。第二是验证闭环：工具负责真实修改和构建，模型再用查询验证人群、粒度和公式；构建成功只说明能执行，最终业务正确性由求解结束后隔离运行的原始 pytest 判断。
>
> 执行过程保存模型用量、补丁和源码版本，组件结果与整题通过分别展示。当前使用 Flash 推理模式，并限制请求与公开验收轮数。具体成绩我会打开 RESULTS 中对应冻结版本说明；个人接手的修改则展示代码 Diff、反例和验证记录。

面试前实际打开一次报告，找到任务说明、候选补丁、目标构建、评分协议、最终判定和费用。能把这六处对应到代码，比背诵框架名称更有帮助。

## 用本轮实际补丁讲两件事

首轮 Flash 四题最终为 **3/4**；商品题构建成功，但原始 pytest 为 **7/11**（7 passed、4 failed），失败记录保留。以下只解释该轮退款、客户两份实际提交，代码依据是候选补丁与公开 instruction，未使用参考解法。本节的组件结果来自本轮独立验收记录。第二轮仅商品的8/11失败已封存；后来的v43契约辅助11/11与八题成品证据见 [RESULTS.md](RESULTS.md)，不回改本节首轮成绩。

### 1. 退款：先限定排名总体，再保留全部退款

公开工单要求仅对非 NULL 的处理天数计算百分位，同时输出全部退款。本轮补丁把排名放入单独关系，关键片段为：

```sql
processing_rank as (
    select
        return_id,
        percent_rank() over (order by total_processing_days desc) as processing_pct_rank
    from with_timing
    where total_processing_days is not null
),
```

这里的 `WHERE` 改变了窗口函数实际看到的行。若天数为 20、10、NULL，排名总体应有两行，10 的百分位为 1；只把 NULL 的最终输出遮住，仍可能按三行得到 0.5。补丁随后从完整的 `with_timing` 左连接排名，NULL 天数退款仍保留，只是没有排名值。

同一补丁还移除了原来的 `REJECTED/CANCELLED` 退款过滤，比率改用项目已有 `safe_divide`，并按工单指定顺序和 NULL 规则生成分类。该题最终目标构建与原始 pytest 均通过，**13/13 组件通过**，证明此次固定题目数据及其验收覆盖下，补丁满足要求。

本机证据：[实际 patch](../external/native-results/refund-v41-flash-r1-verified.patch)、[实际运行 JSON](../external/native-results/refund-v41-flash-r1-verified.json)。对应公开要求位于 `external/data-eng-bench/tasks/dbt-fix-refund-reconciliation/instruction.md`。

随仓库分发的归档：[首轮退款真实回放](../examples/recorded_runs/b0f50ae7-e5f1-55c3-8cb7-4593afcdafeb.json)。

### 2. 客户：恢复覆盖，固定日期基准，保留单位后处理除零

补丁在订单源加入 `customer_id is not null`，保留原有 `status != 'CANCELLED'` 口径；移除聚合后的 `where total_revenue > 0`，让零收入或负收入客户不再仅因收入门槛被丢弃。它没有再猜测新的取消状态别名。

所有时间计算改为引用源数据最大订单日期。这个最大值直接来自公开指定的源模型，而不是运行当天或已过滤订单的最大值：

```sql
    select
        max(ordered_at) as ref_ts,
        cast(max(ordered_at) as date) as ref_date
    from {{ ref('int_sales__orders_enriched') }}
```

除零采用 `NULLIF(分母, 0)`。例如月频次保留原来的自然月差口径，只更换日期基准并处理零分母；没有额外改成“天数÷30”或强设最少一个月：

```sql
        total_orders / nullif(date_diff('month', first_order_date, ref_date), 0) as orders_per_month,
```

其他比率同样保护分母，新增评分再按各自公开规定处理 NULL、权重和范围。该题最终目标构建与原始 pytest 均通过，**15/15 组件通过**。此次 `stop_reason=step_limit`：Agent 达到调用上限，没有最终口头交付，但落盘补丁和独立验收已通过；停止原因、自然语言交付与结果正确性分别记录。

本机证据：[实际 patch](../external/native-results/division-v41-flash-r1-verified.patch)、[实际运行 JSON](../external/native-results/division-v41-flash-r1-verified.json)。对应公开要求位于 `external/data-eng-bench/tasks/dbt-fix-division-by-zero/instruction.md`。

随仓库分发的归档：[首轮客户真实回放](../examples/recorded_runs/904f8b54-db52-5508-ae97-31b6355466aa.json)。

这些是固定公开开发题的本机 Native 验收，适用范围对应本次数据、运行配置和测试；SQL 中存在另一数据库分支，不代表已执行 Snowflake 验证。以上 `external/` 原始路径保留在本机，不随源码导出；两份 `examples/recorded_runs/` 归档可用于离线回放，最新汇总统一见 [RESULTS.md](RESULTS.md)。

前文的分号输入列表支持，以及代码阅读清单中的退款比例语义契约和负净收入 stress 变体，仍是**待做的个人修改**；本轮 Agent 生成的业务补丁与后续个人接手改动分别保留证据。

## 最新修复与适合接手的修改

v41两轮历史成绩保留：首轮3/4、商品补测8/11。后续已完成可审阅的产品归属修复，四份成品原始公开验收全部通过，见 [成品报告](../results/acceptance/public_fixes_20261026.json)。这不是把人工审阅改成Agent成绩。

真实Agent v42仍因收入解释与孤儿键处理失败，7/11。v43从该失败候选继续，向模型明确项目的收入来源、产品归属和事实保全要求后，4次Flash生成了正确SQL，独立build及原始pytest11/11通过。项目契约可见、最终验收不可见；这个结果明确标为契约辅助。[协议与用法](PUBLIC_CONTRACTS.md)说明完整边界。

读码优先顺序：`context.py::_relationship_checks`查看孤儿键证据，`harbor_agent.py::install_public_contracts`查看需求如何进入工作区，`workspace.py::check_contracts`查看可执行反例，最后对照`examples/public_fixes/dbt-fix-product-metrics.sql`和原始失败Diff。不要只加`coalesce(line.product_id, variant.product_id)`：非NULL的孤儿键必须先验证维表存在性。

个人接手可以补一个产品归属冲突的独立测试，先写清直接键与变体键都有效但不一致时的业务规则，再验证不会重复计数；保留自己实际修改的Diff。前文分号输入列表、退款比例语义契约与负净收入stress变体仍按各自代码现状理解，完成后再写入个人贡献。

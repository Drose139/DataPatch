# DataPatch：真实失败、已完成修订与剩余问题

## 当前公开工程续作（两轮已结束）

商品剩余差额的只读SQL、原始与staging对照、孤儿键及唯一变体映射见 [PUBLIC_REMAINING_ISSUE.md](PUBLIC_REMAINING_ISSUE.md)，没有据此回写成绩。

Flash 首轮固定四题 3/4：退款 13/13、客户 15/15、库存 12/12；商品构建成功但 7/11。第二轮仅商品，8/11，仍未通过。合计 55 次调用、保守估算 $0.397302，不再追加模型轮次。[完整验收](ACCEPTANCE.md)保留两轮原始结果；[公开工程指南](PUBLIC_PROJECT_GUIDE.md)用于读码和面试。以下实验按其历史版本解释，不能用旧结论覆盖本次结果，也不能把跨版本开发记录写成最终版四题全通过。

本页记录 2026-10-25 的实际运行与代码审阅发现。模型失败、执行环境故障和评分漏洞分别处理；修好了基础设施或评分器，不等于模型任务表现已经提高。

## 数据来源与实验边界

外部开发案例来自 [Snowflake-Labs/data-eng-bench](https://github.com/Snowflake-Labs/data-eng-bench)，固定 commit 为 `a3278ad102829a6084dde086244a0ef665a8011c`。两题在独立的初始项目目录运行，使用真实 `deepseek-flash`；结束后单独执行上游原始 pytest 断言。适配只重映射本机路径，没有把最终验收反馈送回原次运行中的 Agent。

这是 Windows native 路径的两道**公开开发题**，不是 Docker/Harbor 官方成绩或未见任务泛化证明。v1、v2、v3、v3.1 为同题开发迭代，各轮每题一次，保留相同的分题步数上限；没有运行模式对照或多次独立重复实验。

原始证据：

- 汇总：`artifacts/evaluations/public_native_subset_20261025.json`。
- 退款任务：`external/native-results/refund-verified-02-verified.json`、同名 `.jsonl` 与 `.patch`。
- 客户指标任务：`external/native-results/division-verified-01-verified.json`、同名 `.jsonl` 与 `.patch`。
- v2 重测：`artifacts/evaluations/public_native_v2_20261025.json` 与同名 `.md`。
- R2／R2b 合成回归：`artifacts/evaluations/round2_semantic_review_20261025.json`、`round2b_contract_review_20261025.json`。
- 公开题后续迭代：`artifacts/evaluations/public_native_v3_20261025.json`、`public_native_v31_20261025.json`。
- 外部适配与来源说明：[PUBLIC_BENCHMARK.md](PUBLIC_BENCHMARK.md)。

## v1 实际结果

| 任务 | 模式 | 步数上限／实际模型调用 | 原验收组件通过 | 任务 reward | 工具调用 | Tokens | 估算 USD |
|---|---|---:|---:|---:|---:|---:|---:|
| `dbt-fix-refund-reconciliation` | verified | 24／24 | 12／13 | 0 | 34 | 992,472 | 0.301547 |
| `dbt-fix-division-by-zero` | verified | 16／16 | 1／15 | 0 | 32 | 679,596 | 0.208002 |

任务通过 **0／2**。两题都因 `step_limit` 停止，没有最终自然语言交付。共 40 次模型调用、66 次工具调用、1,672,068 Tokens，按配置单价估算 0.509549 USD；实际账单以服务商为准。

组件部分通过用于定位失败，不折算成整题成功率。退款题少一个组件未通过，整题仍失败。

## 失败一：已写补丁，却在成功查询上停滞

退款题的关键事件按 `step` 可重现：

| 步骤 | 真实事件 | 说明 |
|---|---|---|
| 10 | `write_model`，修改 `rpt_return_reconciliation.sql` | 已产生实际代码变更 |
| 11 | `run_dbt(build, select=rpt_return_reconciliation)` 返回成功 | 构建成功 |
| 12 | 检查唯一行、NaN/Inf 与分层分布 | 查询均有正常结果 |
| 13 | `check_contracts` 返回 `passed=true, available=false, checks=[]` | 当前外部项目没有额外的 DataPatch 可见契约；不表示所有业务规则已验收 |
| 17–24 | 连续 8 次同一 SQL 查询 | 数据库未再修改，结果相同，直到预算耗尽 |

末尾重复查询的核心返回一直是：

```text
columns: n, non_null_rate, non_null_days, non_null_eff, over_refund
rows:    287, 287, 165, 165, 125
```

完整 24 步中有 3 次文件读取、28 次 SQL 查询、1 次模型写入、1 次 dbt 执行和 1 次可见契约检查。末尾重复并非查询失败后的重试；工具已成功返回，模型仍继续请求。

根据当前代码，assistant 工具调用后追加对应 `tool_call_id` 的结果，再请求下一轮模型；没有发现消息排序错误。日志也没有显示同一稳定状态下工具先报成功再报相反结果。因此，目前证据支持“缺少停滞反馈与交付推进机制”，不支持直接归因于工具协议冲突。

## 失败二：查询不断变长，但没有增加信息或交付补丁

客户指标题执行了 3 次文件读取、29 次 SQL 查询，**没有 `write_model`，也没有 `run_dbt`**。

前期模型试图区分订单状态、客户标识与时间字段中的空值。随后查询中的 `NOT IN (...)` 状态集合不断扩展，最后又重复追加已经存在的 `'CANCELLED','cancelled'`。SQL 字符串在变化，业务含义和结果却没有变化。

从第 11 步到预算结束，相同列与零结果共出现 12 次：

```text
columns: n, dcust, null_ts, mx
rows:    0, 0, null, null
```

这说明仅比较“工具名＋完整参数字符串”不足以发现停滞。同义 SQL 或冗余条件仍能绕过精确参数去重。最终验收只有编译组件通过，新增分析列与其他业务要求没有完成。

不能把这一题描述成“仅最后一个边界未修好”；它在预算内没有从数据探索进入代码交付。

## 一个独立的业务错误：CASE 没有改变窗口总体

退款补丁还包含下面的计算模式：

```sql
case
    when total_processing_days is not null
    then percent_rank() over (order by total_processing_days desc)
end
```

这只把 NULL 行的最终输出置空，没有在窗口计算前排除这些行。任务要求只在处理天数非 NULL 的记录中计算分位数；错误总体改变窗口分母，最终 `component_8_waterfall_tier_logic` 失败。

该错误来自结束后的验收分析。原失败补丁没有被手工改成成功记录。此例说明编译成功、列齐全、没有 NaN/Inf，与分层业务语义正确是不同检查。

停滞检测能够减少浪费或促成交付，但它本身不会保证窗口总体选对。业务语义仍需要通过任务约束、可见反例与最终独立验收检验。

## 上下文成本的实际证据

| 任务 | 首次请求输入 Tokens | 最后一次请求输入 Tokens |
|---|---:|---:|
| refund-reconciliation | 33,531 | 44,365 |
| division-by-zero | 34,504 | 46,276 |

v1 的结构化上下文会包含较广的 schema 与模型依赖信息，历史工具消息又随轮次增加。原始 usage 显示，两个案例在开始时就有较高的输入成本，重复请求进一步放大总量。

v2 改为定向选择目标模型、上游依赖和相关表结构，并限制上下文字符预算。同题真实重测已完成，具体成本与失败对比见下文。上下文选择与进度提醒一并修改，不能仅归因于其中某一项。

## 审阅发现的评分漏洞：旧表正确，最终 SQL 却不能构建

原来的 `RunService._execute()` 先执行最终 dbt build，再调用 `verify_task()`，但没有把 build 成功加入任务成功条件。若模型曾构建过正确表，随后提交了无效 SQL，失败的 dbt 执行可能保留旧物化结果。Oracle 读旧表仍能通过，而当时的统计会把整题计为成功。

这个问题已在无模型调用的临时任务中复现：

```text
先物化正确结果
→ 将最终 SQL 改成语法错误
→ final_build.success = false
→ 原 verify_task().passed = true（读取旧表）
→ 原 summarize() 将该记录计为成功
```

**已修复的评分规则：** 任务成功要求运行 `status=completed`、最终构建成功和独立 Oracle 通过三者同时成立；验收增加 `final_build_success` 检查，保留原 Oracle 的所有检查。构建失败的说明明确提示匹配数据可能来自旧表。`completed` 只说明运行流程完成，不能单独代表任务成功。

`tests/test_service.py::test_final_score_requires_build_and_independent_output_checks` 用 FakeWorkspace/FakeAgent 覆盖“旧表正确但构建失败”和“构建及输出都正确”两种情况；两项回归均通过，无真实 API 调用。

54 次合成对照现已全部完成，并按保存的状态、最终构建与 Oracle 证据统一修订评分，没有重跑模型。仅 1 次 context 判定改变：Windows 持久化失败的运行虽然曾通过输出检查，运行状态仍为失败，不能计为任务成功。这一改变来自基础设施失败状态；旧表漏洞则在上述临时任务中复现。

正式报告为 `artifacts/evaluations/synthetic_holdout_20261025.json`；修订前报告另存为 `synthetic_holdout_20261025_unamended.json`，修订原因与改变次数记录在 `grading_amendment`。这是评分修订，不能当作 Agent 策略提升。

## 已发生的执行故障：Windows 拒绝替换运行记录

合成评测中的 `refund_reconciliation_holdout / context` 有一条实际环境错误：

```text
Run ID: c8f7420b-86a5-48cc-8594-da441698f7fa
PermissionError / WinError 5
run.json.tmp → run.json
```

当时记录了 6 次模型调用、9 次工具调用和 17,647 Tokens，失败发生在结果持久化，而不是最终业务验收。可能原因是 Windows 的读者或安全软件短暂占用目标文件；单凭异常无法确定具体占用者。不同进程中的线程锁不能互相协调文件访问。

**已加入代码的修复：** `write_json()` 对真实观察到的 `PermissionError` 做有限次数退避重试，仅重试文件替换，不重新调用模型；持久化回归测试已通过。它降低短暂共享冲突导致任务中断的风险，但不追溯改变原次运行的实际失败。

原失败保留在总体分母与基础设施失败计数中。修订后的 context 为 17／18，其中这 1 次为基础设施故障；没有用后续运行覆盖原记录。

## 已完成的评测与回归

| 运行 | 已完成结果 | 证据与解释 |
|---|---|---|
| v1 合成对照，6 题 × 3 模式 × 3 次 | react 18／18；context 17／18；verified 17／18 | 54 次均已结束；context 的 1 次基础设施失败保留；以修订后 canonical 报告为准 |
| v2 合成 smoke | verified 6／6 | `release_v2_smoke_20261025.json`；独立报告，不并入 v1 对照 |
| v2 两道公开开发题 | 0／2；组件分别 12／13、14／15 | `public_native_v2_20261025.json`；整题失败保留 |
| R1 数据证据回归 | 2／2 | `round1_evidence_20261025.json`；验证快照与前后变化采集后的实际任务运行 |
| R1 真实 UI 验收 | 桌面与 390px 手机通过 | `artifacts/qa/round1_evidence_ui_20261025.json`；新记录数据、旧记录缺失提示与契约状态均已核对，无 JS 错误或额外模型调用 |
| 初次 R2 语义复核合成回归 | 5／6 | `round2_semantic_review_20261025.json`；增量题被错误复核意见引向构建失败，详见下文 |
| R2b 契约约束复核合成回归 | 6／6 | `round2b_contract_review_20261025.json`；52 次模型调用、89 次工具调用、191,325 Tokens，估算 0.063835 USD |
| 公开题 v3 | 0／2 | `public_native_v3_20261025.json`；实际没有发生语义复核，不能算作复核效果实验 |
| 公开题 v3.1 | 0／2；组件分别 12／13、14／15 | `public_native_v31_20261025.json`；两题各复核一次，其后补丁又修改 |

合成 holdout 改变的是同类任务的数据变体，不能据此推断跨项目泛化，也不能从这组结果宣称 verified 优于 react。原 54 次对照使用 v1 策略，冻结源码为 `artifacts/evaluations/synthetic_holdout_20261025_source.zip`；后续评分修订与策略版本分别记录。

## v2 通用改动及实际重测

v2 冻结版本的 `agent.py` 标识为 `v2-focused-context-progress-reminders`，新增以下通用机制：

- 对成功 `query_sql` 的 `columns / rows / truncated` 建结果指纹，忽略耗时。相同状态下同一观察第 3 次出现时，在工具反馈中加入停滞提示。模型写入或成功 dbt 执行后清空统计，保留有意义重验的机会。
- 连续 8 次读操作没有推进写入时提醒；剩余 4 次或 2 次模型调用时再次提示预算，要求实现补丁、执行定向验证，或明确说明阻塞。提示不会替模型填写业务计算。
- `context.py::build_task_context()` 从指令或显式焦点定位目标 SQL，附带有限上游依赖、相关 schema 与来源记录；`_finish()` 控制序列化字符数，目标未找到时给候选文件和进一步工具指引，避免直接注入全库。

与 v1 的同题比较如下，组件通过只用于定位，不折算成整题成绩：

| 项目 | v1 | v2 |
|---|---:|---:|
| 退款题组件通过 | 12／13 | 12／13 |
| 客户指标题组件通过 | 1／15 | 14／15 |
| 整题通过 | 0／2 | 0／2 |
| 总 Tokens | 1,672,068 | 533,419 |
| 估算费用 USD | 0.509549 | 0.168127 |

总 Tokens 减少 68.1%，估算费用减少 67.0%；实际账单以服务商为准。两次 v2 运行仍达到步数上限，分别触发一次停滞提醒。客户指标题已能生成并执行补丁，完成率没有提高。

退款题 v2 补丁使用 `NULLS LAST`，仍未将 NULL 行排除出排名总体，窗口分母问题仍存在。客户指标题把原有 `status != 'CANCELLED'` 改为 `upper(status) <> 'CANCELLED'`，扩大了取消状态的过滤范围，改变原有大小写语义，导致少 2 位客户。

## R2 的真实失败：复核器提出了未经要求的改动

初次 R2 中，`incremental_replay_holdout` 的候选补丁使用 `delete+insert` 和 `unique_key='order_id'` 保证重复输入幂等，保留增量物化。复核器没有收到 README 的完整输出契约，却把“不使用 watermark、每次重算当前状态”提升为正确性问题，要求增加增量过滤。该要求超出了工单对幂等与物化方式的约束。

执行器采纳建议后，使用 `select max(updated_at) from {{ this }}` 读取水位；目标表按契约只包含 `order_id, status, net_cents`，并没有 `updated_at`。最终构建和独立重放都因缺列失败。已有物化表的行值仍正确，但修订后的评分规则将该次记录判为失败。这是复核反馈损害原本正确候选的实际案例，Run ID 为 `8de016ec-37b4-42d4-a542-b144092f6b12`。

R2b 将 README 契约纳入复核上下文，要求每条 finding 引用可见需求或原 SQL，并校验引用确实存在；提示明确禁止把未经要求的性能偏好提升为正确性要求。修订后 6 道合成题全部通过，52 次模型调用中包括复核调用，未把它们排除在成本之外。推荐演示的退款记录为 `e9ed927d-921c-48ac-a521-e223afa31dde`：包含真实数据证据、一次 `approve` 复核，最终独立验收通过，且补丁在复核后没有再变。

公开题 v3 没有触发复核，整题仍为 0／2。v3.1 两题各实际触发一次复核，整题仍为 0／2：退款题 12／13，客户指标题 14／15。两份结果都记录了 `patch_changed_since_review=true`，复核意见对应中途候选，不能覆盖后续最终补丁。

退款题复核已指出 NULL 行参与排名总体的问题，但最终补丁仍未正确排除该总体；客户指标题仍将原始状态过滤扩展为 `upper(status) not in ('CANCELLED', 'C')`，改变允许保留的记录总体，最终行数为 378，原验收要求 382。**语义复核功能已经能够执行并留下证据，但尚未证明提高公开题成功率。**

## 离线审计已实现

`audit.py` 已实现报告协议矩阵、逐次状态与构建、汇总重算、Token 加和、公开 pytest 原始证据及源代码快照绑定校验；对应 24 项测试通过。审计只读取已有报告，不调用模型，也不改写任务成绩。缺少旧版源快照或 manifest 时会留下无法核验的说明；审计通过表示已检查记录内部一致，不证明 Agent 的业务推理正确。

## 已解决与仍存在的问题

| 问题 | 当前状态 | 实际证据或剩余限制 |
|---|---|---|
| 旧表造成评分假阳性、失败状态仍被计成功 | 已修复并重算 | 成功要求 completed＋最终 build＋独立 Oracle；54 次仅改变 1 次 context 判定，原报告保留 |
| Windows 记录替换失败 | 已加有限重试并通过持久化回归 | 只重试文件操作；原实际失败仍保留在分母 |
| 数据变化难以检查 | R1 已完成 | 前后行数、schema、键匹配样本与契约状态可回放；变化本身不证明正确性 |
| 上下文过宽、重复查询消耗 | 已缓解，未消除 | v2 同题 Tokens 和估算成本下降；仍到达步数上限，提醒未保证最终交付 |
| 复核器缺少契约并提出越界修改 | 已修订，R2b 合成 6／6 | 纳入 README、校验需求引用；不能据小样本宣称消除误判 |
| 复核意见未覆盖最终补丁 | 公开 v3.1 两题均实际发生 | 各复核一次后又修改；记录已标记，不能把中途 approve／revise 当成最终验收 |
| 退款窗口计算总体错误 | 仍存在于公开题 v3.1 结果 | 12／13 组件通过，整题失败 |
| 客户指标擅自改变过滤语义 | 仍存在于公开题 v3.1 结果 | 14／15 组件通过，378 行而非 382 行，整题失败 |
| 报告协议与汇总缺少独立核验 | 离线审计已实现，24 项测试通过 | 校验可复现记录与评分一致性；旧产物缺少的来源证据仍明确保留 |

各轮报告与源码快照分别保留，R2b、公开 v3.1、R1 数据证据回归均不并入原 v1 54 次对照。

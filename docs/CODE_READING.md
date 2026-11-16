# DataPatch：投递前读码与修改清单

原四题Agent轨迹先看 [公开工程指南](PUBLIC_PROJECT_GUIDE.md)，八题成品与验收策略看 [八题说明](PUBLIC_EIGHT_TASKS.md)，实际成绩单独看 [RESULTS.md](RESULTS.md)。下文公开两题 0/2 对应历史 v1～v3.1，保留原数字和失败分析，不作为后续四题的当前结论。

先沿一份真实运行读懂“模型如何行动、代码如何执行、结果如何验收”，再看领域上下文、变更证据与实验统计。下面共 11 处，按优先级排列。项目初版采用 AI 辅助开发；个人贡献以实际审阅、修改和验证记录为依据。

## 从一份真实记录开始

工作台「运行记录 → 运行数据」对应 `artifacts/runs/<run_id>/run.json`。选出一次工具调用、代码 Diff、`data_evidence`、`candidate_review` 和最终 `verification`，逐项定位来源。历史记录可能没有后续版本新增的字段。

`status="completed"` 表示流程结束；`verification.passed` 表示本次最终构建和独立验收满足条件。before/after 展示实际数据变化；最终构建失败时，after 中可读取的表可能仍是旧物化结果。

先看 `provider`、`mode` 和 `recording_source`：真实 Agent 回放、`operator_reviewed/reviewed_patch` 成品验收回放分别解释。商品成品记录 `bfd1ddf6-c4a0-56bd-9435-4003b3f1d570` 是原 pytest 11/11 的真实验收，模型指标为零，没有模型推理事件；首轮退款 `b0f50ae7-e5f1-55c3-8cb7-4593afcdafeb` 才适合跟读模型如何选择工具。公开记录没有快照时，不应期望出现 `data_evidence`。

## 有主次的 11 处

| 顺序 | 代码位置 | 需要读懂的重点 |
|---|---|---|
| **1：执行主线** | `src/datapatch/service.py`：`_execute()` | 创建任务 → seed/run → Agent → 最终 build → 独立验收 → 保存产物。最终构建与 Oracle 取 AND；`data_evidence` 保存前后快照、构建状态和可见检查。 |
| **2：决策与预算** | `src/datapatch/agent.py`：`run()`、`_run()`、`_response()` | 模型与工具如何往返；模式开关与进度提醒。`verified` 在剩余调用 ≤6、累计只读探索 ≥8 且没有候选时进入预算收尾阶段，暂收只读工具，写入后恢复。`max_steps≥6` 时才启用最多一次候选复核，占同一调用预算；少于 6 次的短修复跳过。看 `delivery_stage_entries`、`review_calls`、`stop_reason` 与总调用数。 |
| **3：工具执行** | `src/datapatch/workspace.py`：`call()`、`write_model()`、`query_sql()`、`run_dbt()`、`check_contracts()` | SQL 写入范围、只读探查、dbt 子进程与结构化错误；可见检查返回违规行。区分检查不存在、执行失败与确实通过。v4.4显式UTC由case元数据传给工具和context连接，默认宿主行为保留。当前是可信本机执行，文件与工具约束属于应用层。 |
| **4：聚焦上下文** | `src/datapatch/context.py`：`build_task_context()`、`_candidate_paths()`、`_relationship_checks()`、`_finish()` | 依据工单路径或 `focus_model` 选择目标 SQL；缺失目标从公开输入名选择有限来源。`relationship_checks` 对选中表的同名同类型 ID 列检查唯一性、NULL、孤儿及候选关系；它是全输入证据，不能代替筛选后的业务归属规则。README、schema、上游、画像共用 24,000 字符预算，记录裁剪。详细限制见 [RELATIONSHIP_CHECKS.md](RELATIONSHIP_CHECKS.md)。 |
| **5：数据与标准答案** | `src/datapatch/fixtures.py`：`_SPECS`、`_data()`、`create_task()`、`_oracle()`、`verify_task()` | 6 类 × dev/holdout 共 12 个任务；生成目录没有 Oracle 或参考修复。最终 Python 计算独立核对所有行，并检查源数据完整性；增量任务重跑相同 delivery 验幂等。 |
| **6：数据变化证据** | `src/datapatch/evidence.py`：`capture_output()`、`compare_outputs()` | 只读真实表，记录 schema、全表行数和声明键的有效性；行快照最多 5000 条。键缺失、重复、NULL 或快照截断时不产生伪全量 keyed diff；差异本身不判断正确性。 |
| **7：提交前复核** | `src/datapatch/review.py`：`review_candidate()` | 调用方启用且有预算时，同一模型用新上下文审公开要求、原 SQL 与候选补丁。finding 的 `requirement_quote` 必须匹配真实工单、README 或原 SQL；无据建议被过滤。意见仍是建议；过大核心材料跳过。对照候选哈希和 `patch_changed_since_review`，判断审阅对应哪个补丁。v4.3 的四调用短修复没有候选复核。 |
| **8：实验统计** | `src/datapatch/evaluation.py`：`evaluate()`、`summarize()` | 请求前冻结任务、配置、预算和代码摘要；每次真实运行保留。单次通过率、每题重复全通过率、基础设施失败、Token 与估算成本分别查看。 |
| **9：模型调用** | `src/datapatch/provider.py`：`DeepSeekClient._output_allowance()`、`complete()` | 强制 Flash；按输入 UTF-8 字节和输出上限预留估算预算，可缩小输出，剩余可用输出不足 512 时在 HTTP 前停止。网络、超时和 HTTP 错误均不自动重试。Token 来自响应，推理明细不重复加总；审阅也走同一计量入口。 |
| **10：离线审计** | `src/datapatch/audit.py`：`audit_report()`、`audit_reports()`；`scripts/audit_results.py` | 已实现对报告、逐次记录与源码快照的只读核对：覆盖、run ID、最终构建判定、Token/费用和汇总。模块回归已通过，当前完整测试结果见 ACCEPTANCE.md；最终交付报告的审计输出见总验收记录。 |
| **11：公开契约与验收来源** | `integrations/harbor_agent.py`：`install_public_contracts()`、`run_native_case()`、`verify_target_build()`、`render_public_summary()`；`examples/public_contracts/product/` | 调用方显式把 SQL 检查与 README 安装进 case 的 `checks/`；另存 `solver-instruction.md`，原工单不改。记录契约文件哈希、`public_contracts` 和开始时 `target_start`，区分从原任务开始与失败候选 continuation。Agent 停止后才运行 case 外原 pytest。已审阅成品另走 `scripts/verify_public_fixes.py` 和 `export_reviewed_recordings.py`，不混入自主评测。 |

前 3 处负责一次任务闭环；第 4–7 处解释领域取舍；第 8–10 处解释数字如何得到与复核；第 11 处串起当前公开工程。前端在 `src/datapatch/static/`，通过 `web.py` 调用服务。四种 Agent 模式之外的 `reviewed_patch` 仅用于验收回放，不能当成第五种可启动 Agent 策略。

公开题的运行环境再看三处：`integrations/run_public_pytest.py`只统一独立DuckDB连接时区并保留pytest退出码；`integrations/public_packages.py`验证同版本依赖的234文件SHA及原安装证据；`scripts/export_reviewed_recordings.py`区分真实模型、成品验收和准备失败未执行，缺失的SQL/测试证据不补造。对应反例在`tests/test_session_consistency.py`、`test_public_packages.py`和`test_reviewed_recordings.py`。

离线审计入口：`audit_report(report, report_path=...)` 返回 `passed/errors/warnings/checks`；`audit_reports(paths, include_unamended=False)` 聚合报告并列出排除项。默认明确排除 `_unamended` 历史报告；预审计实际检出过修订前报告中的一条失败误标通过。命令用法和检查范围见 [EVALUATION_AUDIT.md](EVALUATION_AUDIT.md)。

## 读数时对应版本

| 已完成记录 | 事实 | 阅读重点 |
|---|---|---|
| 冻结的合成重复评测，54 trials | ReAct 18/18，context 17/18，verified 17/18 | 6 个相同问题类型的新数据任务 × 3 模式 × 3 次；context 的 1 次 Windows 存储基础设施故障仍保留在分母。 |
| v2 六题 smoke | 6/6 | 单独的功能回归记录，与 54 次重复实验分开。 |
| 公开两题 v1 → v2 同题开发重测 | 两版均 0/2；总 Tokens 1,672,068 → 533,419，减少 68.1% | 执行效率改善与整题成功分别观察；公开 Windows Native 开发子集。 |
| R2 初次六题回归 | 5/6 | 独立复核缺少 README，误导增量模型添加未要求的 watermark，并引用不存在的列；失败记录保留。 |
| 公开 v3 两题 | 0/2；605,948 Tokens | 组件 12/13、1/15；预算耗尽，两题均未实际触发复核。 |
| R2b 修订后六题回归 | 6/6；52 次模型调用、89 次工具调用、191,325 Tokens | 估算 $0.063835，平均 96.59 秒；组合修订包含 README 回退、需求引用校验和预算收尾。 |
| 公开 v3.1 两题 | 0/2；563,985 Tokens | 组件 12/13、14/15；估算 $0.182636。两题各复核一次，随后补丁均有变化，未再次审阅。 |
| 公开 v4.1 Flash 两轮 | 首轮 3/4；第二轮商品 8/11、整题失败 | 55 次调用，估算 $0.397302；两轮各按源码快照解释。 |
| 已审阅成品验收 | 4/4；商品原 pytest 11/11 | `operator_reviewed`；新工程实际 dbt 与原 pytest，验收零模型调用，不是自主 Agent 4/4。 |
| v4.2 通用关系剖析确认 | 商品 7/11、整题失败 | 12 次 Flash 调用，估算 $0.076260；从原公开创建任务开始，没有额外项目业务契约。 |
| v4.3 项目契约辅助继续修复 | 商品 11/11；4 次调用、62,455 Tokens，估算 $0.021761 | 在 v4.2 失败候选上安装显式项目契约，`step_limit` 后独立构建和原 pytest 均通过；不是原工单无辅助或未知新题成功。 |

报告入口：[RESULTS.md](RESULTS.md)、[三轮改进与验收](IMPROVEMENTS.md)。旧运行按其源码快照与 `agent_revision` 解释；新版 evidence/review 的存在不会改变旧轨迹。历史 v1～v3.1 公开两题各版均为 0/2，其整题成功率没有改善；最新公开四题结果另行查看。复核发生过与最终补丁已获批准是不同事实。

## 两项尚未实现、可由自己完成的修改

以下两项截至本页更新均未实现。选一项完成，保留代码 Diff、明确反例与验证记录；完成后再把它写入个人贡献。

### A：补退款比例的语义契约

当前可见退款检查主要验证覆盖与数值有限性。增加 `refund_ratio_semantics`：申请金额大于零时，比例等于 `paid_cents / requested_cents`；申请金额为零时，比例为 `0.0`。

1. 修改 `fixtures.py::_visible_checks()`，返回违反关系的记录，写明浮点容差。
2. 加一个“比例恒为 0.0”的反例：它满足有限性，对正数已付款退款却不正确。
3. 保持独立 Oracle 不变；新建一个有版本说明的运行，观察反馈是否改变行为与最终结果。

能讲清的取舍：业务不变量应表达具体计算语义；一个绿色的有限性检查覆盖范围有限。

### B：增加净收入为负的 stress 数据变体

当前 LTV 契约为 `net_cents = gross_cents - refund_cents`。增加一个明确命名的新数据变体，让一位客户累计实付退款超过商品收入，检查模型是否擅自把负数截成零。

1. 新增 stress 变体，保留现有 dev/holdout 种子与已发布报告。
2. 让独立 Python Oracle 按原定义自然算出负净收入；期望值留在评估侧。
3. 验证正确 SQL 能通过，而 `greatest(net_cents, 0)` 被拒绝；同步更新任务目录测试。
4. 为新数据版本单独出报告，记录任务集合与源码摘要。

能讲清的取舍：反例挑战未经授权的业务假设，数据规模增加只是次要变化。

## 个人接手后留下的三样证据

- 能定位到函数的代码 Diff。
- 一次真实运行，或一个明确标记为测试的执行级反例。
- 对改动前后行为、结果与适用范围的解释。

初版的 AI 辅助开发、自己完成的审阅和新增修改分别说明，面试时直接打开对应记录即可。

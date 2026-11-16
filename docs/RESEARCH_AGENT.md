# Agent 运行时与数据修复项目调研

调研日期：2026-10-25。目标是给 DataPatch 下一轮提供能落地的通用机制，不读取或借用公开题的参考补丁。结论：优先补充**候选补丁的语义变更审阅、有界结束状态和独立结果核验**；继续增加提醒文字不足以解决当前问题。

## 当前证据

v2 两道公开开发题均未通过完整验收：退款题 12/13 组件通过，客户指标题 14/15 通过，任务结果仍是 0/2。两次都达到步数上限。聚焦上下文让总 Tokens 相比 v1 减少 68.1%，但没有提高二元任务成功率。这些是同题开发重测，不能当作未知任务泛化结果。

客户指标题最初只有一次 schema 查询错误，随后已恢复；主要停滞是不断修改、扩大 `NOT IN` 列表，执行语义等价的聚合查询。退款题反复查询已经成功返回的结果。v2 当前运行时会给相同结果和读取过多的提醒，仍把是否停止、提交或转入修复交给模型。

## 一手项目与实际机制

### 1. mini-swe-agent：显式结束和资源上限

[仓库](https://github.com/SWE-agent/mini-swe-agent)；[DefaultAgent 源码](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py)。

具体观察：`query()` 在下一次请求前检查步数、累计费用和墙钟时间；连续格式错误另有退出条件。`run()` 在循环的 `finally` 中保存轨迹，以明确的 exit 事件结束。源码也说明费用上限在已消费费用基础上判断，不能误称绝不超限。

适用：把 `completed`、`step_limit`、`cost_limit`、`no_progress` 分开保存，异常和预算退出也保留候选补丁与执行证据。

不采用：迁移其完整 bash 工具环境不能解决 SQL 业务语义；DataPatch 现有有边界的文件、查询和 dbt 工具继续保留。资源限额不是正确性证明。

### 2. OpenHands Software Agent SDK：提醒后仍可硬停止

[仓库](https://github.com/OpenHands/software-agent-sdk)；[停滞检测测试](https://github.com/OpenHands/software-agent-sdk/blob/main/tests/cross/test_stuck_detector.py)；[启用示例](https://github.com/OpenHands/software-agent-sdk/blob/main/examples/01_standalone_sdk/20_stuck_detector.py)。

具体观察来自测试：覆盖重复 action/observation、连续错误、模型独白和新用户消息后的重置；其中重复错误先产生 nudge，继续重复会判定 stuck。示例通过 `Conversation(stuck_detection=True)` 启用检测。这里核实的是测试行为，不声称通读了全部运行时实现。

适用：DataPatch 的单次提醒可升级为“提醒→继续无进展→停止并交付部分结果”，按补丁版本、构建反馈重置状态。SQL 参数文本不同也可能语义等价，不能仅按工具参数字符串判重。

不采用：不同检查恰好都返回 0 不代表卡住。应结合读写阶段、查询结果、工具错误和最后一次修改，而不是对相同 COUNT 值直接硬停止；本轮无需引入完整 SDK。

### 3. SWE-agent：保留候选补丁和提交审阅接口

[仓库](https://github.com/SWE-agent/SWE-agent)；[agents.py](https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/agent/agents.py)。

具体观察：`forward_with_handling()` 对格式和语法错误做有上限的重新请求；上下文、费用、重复超时等结束会走 `attempt_autosubmission_after_error()`。外层提交后有 `ReviewSubmission` 和 retry-loop 接口，轨迹持续落盘。

适用：独立设置“候选补丁已保存”和“交付验收已通过”两个状态；提交阶段审阅工单、差异和可见检查结果。达到预算时保存真实状态，不把模型最后一句话当验收。

不采用：本轮不移植完整重试框架，也不把最终隐藏验收接到 reviewer 后不断重跑。可见业务契约与最终评分必须继续隔离。

### 4. ADE-bench：任务级成功与关系结果比较

[仓库及 README](https://github.com/dbt-labs/ade-bench)。

核实到的 README 机制：任务可以复用 dbt 项目；配置目标关系后可自动生成比较测试。一个任务即使有多个评价条件，最终评价单位仍是整个任务。

适用：把关系存在、结构、粒度、覆盖范围和业务值分别检查，最终任务成功仍要求所有必要条件成立。审阅界面应同时展示原始失败和二元任务结果。

不采用：自动关系比较依赖可信的期望关系。不能让求解 Agent 自己生成“标准答案”再给自己评分；也不能把若干组件通过率换算成任务成功率。本轮只借验收组织方式，暂不再引入另一套运行环境。

### 5. Snowflake data-eng-bench：执行结果验收与基准隔离

[仓库](https://github.com/Snowflake-Labs/data-eng-bench)；[固定版本 README](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/README.md)；[官方方法介绍](https://www.snowflake.com/en/blog/engineering/data-eng-bench-data-engineering-agent-benchmark/)。

本地已核验固定源码、原始数据哈希和任务环境。103 道任务在真实 dbt 项目上构建或修改模型，最终 verifier 检查物化结果；DuckDB 路径不要求 Snowflake 账号。项目还强调阻断运行时搜索公开参考解法。

适用：继续保存 patch、实际执行记录和独立 verifier。SQL 可以运行与业务输出正确是两项不同事实；当前公开开发记录正说明这一点。

不采用：不根据已公开的解法或验收反例编写题目专用补丁；不把本地路径适配成绩包装成官方 Harbor 成绩。具体 verifier 强度不统一，也不能一概声称每题完整逐行检查。

### 6. SQLMesh：把逻辑变化当作需审阅的变更

[仓库](https://github.com/SQLMesh/sqlmesh)；[plan 文档源码](https://github.com/SQLMesh/sqlmesh/blob/main/docs/concepts/plans.md)；[audit 文档](https://sqlmesh.readthedocs.io/en/stable/concepts/audits/)。

具体观察：计划区分 breaking/non-breaking；修改 `WHERE` 属于可能改变下游行集的 breaking change。输出 audit 查询返回违规行时，可阻断计划或后续执行；计划环境与直接生产运行的影响不同。

适用：交付前结构化展示过滤条件、连接条件、窗口总体和输出粒度的变化，要求与工单授权对应；可见数据审计返回具体反例，而非单个绿色标记。

不采用：本轮不把 dbt 改写为 SQLMesh，也不做生产推广、环境虚拟化或回填平台。SQL 结构 diff 可以发现风险，不能证明两段 SQL 数学等价。

## 建议的一轮实现边界

### A. 任务语义与变更审阅

在修改前，从**可见工单与原模型**记录 `requested_changes` 和 `must_preserve`；候选补丁产生后，比较被改动的过滤、连接、分组和窗口定义，输出审阅清单。审阅可以使用一次有预算上限的独立模型调用，但结果必须与执行证据分开。

这项机制针对通用风险：没有授权的大小写归一化、连接类型变化、额外删除行、窗口排名总体变化。不能用公开题 ID、预期行数或隐藏反例触发分支。题目要求改变行集时，不能直接要求新旧输出完全相同；原模型本身也可能有错。

第一轮验收至少覆盖：修改明确获准时能够通过；未授权变更会产生审阅项；SQL 操作符的等价写法不会被当作业务变化；不能解析时明确标为未验证。引入 SQL AST 工具之前需额外核验其 Jinja/dbt 与 DuckDB 兼容性。

### B. 结束阶段由运行时负责

达到连续无进展阈值后升级为有界结束阶段，执行已有可见检查并保存候选补丁；没有补丁则交付实际阻塞原因。记录 `candidate_saved`、`visible_checks_passed`、`final_verifier_passed` 和 `stop_reason`，避免一个含糊的 success 字段覆盖所有状态。

验收使用离线伪模型和假工具即可：完全重复查询、参数不同但同观察、正常修复后重新构建、预算耗尽但已有补丁。硬停止的价值先体现在可预测成本和诚实交付，不能预设会提高正确率。

### C. 离线结果审计先补齐

核验任务×模式×重复次数是否真的执行、run ID 是否重复、汇总是否可由逐次结果重算、失败记录是否被误标通过、Token/费用是否自洽、源码快照是否匹配。历史版本和后续修正分别保留，明确排除项。此项无需新增 API 费用，能直接提高简历数字与报告的可复核程度。

## 本轮未采用与证据边界

- 完整迁移 OpenHands/SWE-agent：会增加工具与环境集成，尚无证据表明可解决当前两类 SQL 语义错误。
- SQL 格式化器：格式、解析和编译检查有价值，但不能单独识别合法 SQL 的业务错误。
- 同题反复调参后称“保留集提升”：公开开发题继续保留为开发记录；泛化验收另设新的预登记任务。
- dbt-audit-helper、SQLGlot 等是下一步可核验候选，本轮未取得足够具体源码证据，不把它们计入已完成机制核查。

首次检索取得了上述官方源码、测试或 README 段落。随后 web 工具连续连接失败，GitHub API 对六个仓库的直接读取均出现 TLS EOF；因此未虚构未能读取的内部实现或 commit 锁定。mini-swe-agent、OpenHands、SWE-agent 的说明基于已取得的具体代码/测试片段；ADE-bench 基于 README 段落；SQLMesh 基于官方文档；Snowflake 基于本地固定 commit。除 Snowflake 外，上游链接指向可变分支，采用依赖前应固定版本并复核。

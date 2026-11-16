# 数据变更验收调研：DataPatch 应补哪些证据

调研日期：2026-10-25。本文核查开源仓库和官方文档，提出实现取舍；**没有安装下述产品、修改核心执行器或调用模型 API，也没有把建议写成已实现成果。** 文中的 DataPatch 失败来自已保存的真实开发轨迹；原始记录与统计见 [FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md) 和 [PUBLIC_BENCHMARK.md](PUBLIC_BENCHMARK.md)。

## 结论与优先级

优先补一个由确定性代码生成的“变更验收包”：**构建来源 → schema/行数 → 有效键上的行差异 → 业务契约 → 补丁范围**。它应在 Agent 停止后生成，供用户和面试官直接审阅；可见契约的反例仍可在执行中反馈。最终独立验收器和隐藏答案不进入 Agent 上下文。

这样能把“Agent 说修好了”变成可检查的事实。它不能独自证明因果归因、所有业务规则正确或生产可用。修复前的模型本来就可能错误，因此“和原结果相同”也不能作为通过条件。

| 优先级 | 建议 | 对应的真实问题 | 成本与收益 |
|---|---|---|---|
| P0 | 目标模型修复前后 schema、行数、键的 NULL/重复数 | v2 客户指标任务少 2 位客户；需要迅速看到人群变化 | DuckDB 聚合即可，无新服务 |
| P0 | 有效主键上的 added/removed/changed 及少量逐列样本 | 大小写过滤语义改变，最终聚合数字不足以解释影响 | 用目标表小快照与外连接生成，无需引入整套平台 |
| P0 | 公共业务契约的前后失败数及反例 | 退款模型构建成功、没有 NaN/Inf，但窗口总体仍错 | 复用现有 singular SQL checks；规则来自公开需求 |
| P0 | 最终构建成功与当前代码绑定；失败时标明输出可能陈旧 | 已复现“旧表正确、最终 SQL 无法构建”评分漏洞 | 当前 AND 评分规则已修；证据包继续呈现其结果 |
| P1 | 补丁文件清单、增删行、目标外修改提示 | 防止无修改交付和无必要的全文件重写；帮助审阅过滤条件变化 | 复用现有 diff；不能把行数少当成语义正确 |
| 暂缓 | 长期异常检测、全仓库监控、跨云环境部署 | 当前主要是独立修复任务，缺少持续时间序列 | 建设与评测成本高，不能直接解决已见失败 |

## 一手项目与机制

### 1. DataRecce / recce：把代码变化转成数据影响

一手入口：[官方仓库](https://github.com/DataRecce/recce)、[Data Diffing 官方文档](https://docs.reccehq.com/what-you-can-explore/data-diffing/)、[Lineage 与 Schema Diff](https://docs.datarecce.io/features/lineage/)、[MCP 工具说明](https://docs.reccehq.com/setup-guides/mcp-server/)。

Recce 将行数、列统计与实际值对比分开。Value Diff 按主键匹配，并区分新键、消失的键和公共键上的值变化；文档说明可从 `unique` 测试推断键。其 profile 包括空值、不同值数量及数值范围等；schema 对比依赖两边对应的项目产物。[机制来源](https://docs.reccehq.com/what-you-can-explore/data-diffing/)

**采用：** 使用“代码 diff 与数据 diff 并排”的交付方式；把行数差异当入口，再给 changed keys 和具体列。DataPatch 的每个任务有明确输出表，首版只比较该表，不生成整仓库血缘大图。

**不直接采用：** 当前不启动 Recce 服务或接其 MCP。现有 DuckDB、diff 和任务目录足够实现目标表证据，集成另一套环境和状态管理会增加交付面。Recce 的单环境模式若缺少 base 产物，diff 不代表真实两边对比，DataPatch 也必须显式记录基线是否可用。[环境限制](https://docs.reccehq.com/setup-guides/mcp-server/)

### 2. SQLMesh：grain、行对比与执行后审计

一手入口：[原 TobikoData/sqlmesh 仓库入口](https://github.com/TobikoData/sqlmesh)（现重定向至 SQLMesh/sqlmesh）、[Table Diff](https://sqlmesh.readthedocs.io/en/stable/guides/tablediff/)、[Audits](https://sqlmesh.readthedocs.io/en/stable/concepts/audits/)、[Plans](https://sqlmesh.readthedocs.io/en/stable/concepts/plans/)。

SQLMesh table diff 先比较字段增删与类型变化，再在兼容列上用外连接比较数据。文档提醒 grain 应有唯一和非空审计；不满足时，对齐结果不可靠。两张物化对象需要已存在，不能把“计划中的 SQL”直接当成真实数据变化。[对比机制](https://sqlmesh.readthedocs.io/en/stable/guides/tablediff/)

**采用：** keyed diff 前先验证键。键重复或为 NULL 时，报告 `key_invalid`，展示重复样本与数量；停止声称一对一 changed count。行数、schema、总量检查仍可继续。

**采用：** 将构建与检查分成状态清晰的阶段。SQLMesh audits 对查询返回的违规行判失败，并能阻止后续执行；其文档区分隔离计划发布与直接修改现有表的运行行为。[审计机制](https://sqlmesh.readthedocs.io/en/stable/concepts/audits/)

**不直接采用：** 不把 DataPatch 迁移为 SQLMesh 项目，也不实现环境晋升、restatement 与全范围 backfill。当前增量任务只验证同一 delivery 的重复运行幂等性。表格 diff 的结果与业务正确性分别展示，避免把旧模型当作正确答案。

### 3. dbt：公开契约与改动范围

一手入口：[dbt-core 原仓库入口](https://github.com/dbt-labs/dbt-core)、[官方 data tests 文档](https://docs.getdbt.com/docs/build/data-tests?version=1.12)。仓库入口目前重定向至 dbt-labs/dbt；本文机制依据官方文档，不依赖仓库命名或最新版运行时。

dbt data tests 使用返回违规记录的 SELECT，零违规行为通过。内置规则涵盖唯一、非空、允许值与关系约束，也支持业务专用 singular tests。失败结果可保存下来用于检查。[测试机制](https://docs.getdbt.com/docs/build/data-tests?version=1.12)

**采用：** 继续复用 DataPatch 现有 `checks/*.sql`：把 `available=false`、未执行、执行错误、违规数大于零和通过明确分开。外部项目没有 DataPatch 附加 checks 时，不能因空列表得到 `passed=true` 就宣布业务通过。

**采用：** 从公开工单提取可执行契约，并保存“规则来自哪段公开需求”的映射。以非 NULL 处理天数作为排名总体、精确保留已有状态过滤语义，应分别形成检查；仅检查数值有限与范围不足以覆盖这两项。

**不采用：** 不把上游隐藏 verifier 复制成 Agent 可见测试，不在冻结实验中途追加规则后继续沿用旧结果。若根据公开开发失败增加契约，应保存新版本，重新登记实验；对既有 54 trials 的冻结协议和快照不作追改。

### 4. Elementary：历史监控与单次变更验收的边界

一手入口：[elementary-data/elementary 官方仓库](https://github.com/elementary-data/elementary)、[官方发布的 dbt Package Hub 条目](https://hub.getdbt.com/elementary-data/elementary/latest/)。

Elementary 提供 dbt 原生数据可观测性；发布条目列出数据量、新鲜度、列分布与 schema 变化等检测范围。它回答持续运行中“和过去相比是否异常”，与一次工单“这个补丁是否符合明确契约”的问题存在交集，但不等价。[官方发布说明](https://hub.getdbt.com/elementary-data/elementary/latest/)

**采用：** 借鉴可追溯的运行、测试和指标记录方式，将 schema/行数/键统计与 run ID 绑定，后续能够复看同一变更的证据。

**暂不采用：** 不增加长期历史表、告警服务、统计异常阈值和消息通知。现有任务只有固定输入与有限重复实验，时间序列不足，硬加异常检测容易把修复应有的数据变化当作异常。Elementary 是后续真实持续数据管道的候选集成，不是当前正确性判定依赖。

## 结合 DataPatch 真实失败的设计

### A. 客户少 2 位：先看键集合，再判断变化是否被授权

v2 客户指标补丁将 `status != 'CANCELLED'` 改为 `upper(status) <> 'CANCELLED'`。最终原验收通过 14/15 个组件，但整题失败；验收后分析发现少了 2 位客户。[本地实际记录](FAILURE_ANALYSIS.md)

行数差异能够提示问题，removed keys 和对应订单状态更便于解释。但初始模型也有过滤错误，修复本来就可能增加人口，**净行数差异可能掩盖同时发生的错误删除**。因此验收包应分别给出 added 和 removed 的键，不只给 `after_count - before_count`。最终是否允许改变人群，要依据工单和明确保留的过滤规则，而不是机械要求和旧表相同。

### B. 退款排名错误：schema 和总行数都可能保持正常

v1 和 v2 退款题都通过 12/13 个组件，仍因 waterfall 业务逻辑失败。`CASE` 或 `NULLS LAST` 不能把 NULL 行排除出窗口总体；行数、列结构、无 NaN/Inf 都不足以证明排名总体正确。[失败分析](FAILURE_ANALYSIS.md)

这里需要规则定向的反例：构造很少量非 NULL 天数和 NULL 天数，核对“先排除 NULL，再排名”的结果。这样的可见契约只能来自工单公开要求，不能读取上游最终 verifier 或其答案。before/after 的 tier 改变样本有助于审阅，但不能替代独立语义检查。

### C. 无修改与旧表：区分本次执行事实

v1 客户指标题没有产生模型修改；另一次评分审阅发现最终构建失败时仍可能读取旧表而误判。项目已将最终构建成功与独立 oracle 结果取 AND。[评分漏洞与修复](FAILURE_ANALYSIS.md)

证据包应保留 `code_hash`、构建是否成功、输出表是否存在与采集时间。当最终构建失败，数据快照可供诊断，但标为“不能证明最终代码已产生这些数据”。对明确要求修复的任务，补丁为空时也应直接标识“没有提交代码变更”。

## 建议的最小实现合同

下面是提案字段，不是当前已完成 API。

```text
change_evidence
  provenance: run_id, model, before_code_hash, after_code_hash,
              before_build_success, final_build_success
  schema: added_columns, removed_columns, changed_types
  counts: before_rows, after_rows, key_nulls, duplicate_key_groups
  keyed_diff: status, keys, added_count, removed_count, changed_count,
              unchanged_count, sample_added, sample_removed, sample_changes
  contracts: available, executed, failures_before, failures_after, examples
  patch: changed_files, added_lines, removed_lines, outside_target_files
```

实现顺序：

1. 可信执行器在修改前保存目标模型的小快照及 schema。大型外部仓库只取目标表，不复制整个 489MB 数据库。快照写到 Agent 工作区之外；若基线无法新鲜构建，记录缺失状态。
2. 最终构建完成后，读取目标输出并生成差异。比较共有且兼容的列；列增删另列 schema diff。键通过唯一和非空检查后再对齐；多列键作为联合键，不拼接易碰撞的字符串。
3. 用 NULL 安全比较（DuckDB 的 `IS DISTINCT FROM`）识别 changed cells；金额用整数分严格比较。浮点容差单独记录，不为报告好看而四舍五入隐藏差异。
4. 每类样本最多 5 条，完整数量与样本分别标注。样本不代表全量已经检查；如果采用抽样对比，必须明确 `sampled=true`。
5. 将现有公开 contracts、最终构建状态、补丁范围和隐藏验收结果分开保存与展示。隐藏验收仍是结束后的独立评分，不作为执行中工具。

## 验收方式与不采用项

实现后首先用无需模型 API 的三类确定性测试验证证据质量：

- 造一个行数不变但某个键被替换、金额被改变的前后表，必须分别报告 removed、added、changed。
- 造重复/NULL 键，必须给出 `key_invalid`，不输出伪一对一匹配率。
- 先保留正确旧表、再提交无法构建的 SQL，最终交付必须失败，旧快照不得被标成新代码成功产物。

不把“changed rows 越少”当作优化指标：正确修复可能改变所有行。也不以修改行数少、行数一致、schema 一致、检查列表为空中的任何单项代替业务正确性。

外部来源页面与仓库内容在本轮成功检索后，补充访问部分文档/raw 文件遇到网络连接失败；未读取到的 unit-test/state-selector 详细实现没有作为本文机制依据。本文未报告这些工具的实测性能或兼容性。

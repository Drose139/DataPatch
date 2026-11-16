# 调研、三轮改进与验收

## 当前公开工程续作（两轮已结束）

Flash 首轮固定四题 3/4：退款 13/13、客户 15/15、库存 12/12；商品构建成功但 7/11。第二轮仅商品，8/11，仍未通过。合计 55 次调用、保守估算 $0.397302，不再追加模型轮次。[完整验收](ACCEPTANCE.md)保留两轮原始结果；[公开工程指南](PUBLIC_PROJECT_GUIDE.md)用于读码和面试。以下实验按其历史版本解释，不能用旧结论覆盖本次结果，也不能把跨版本开发记录写成最终版四题全通过。

第一版先完成真实 DeepSeek 执行、CLI／网页、独立业务验收和真实运行回放，再开展本轮调研。日期：2026-10-25。

## 调研结论

交叉核查了 14 个一手开源项目与官方文档，详细记录分为 [Agent 运行时](RESEARCH_AGENT.md)、[数据变更验收](RESEARCH_DATA.md)、[产品与评测](RESEARCH_PRODUCT_EVAL.md)。部分后续源码抓取遇到网络故障，三份文档分别标明实际取得的证据。

| 参照项目 | 借鉴机制 | DataPatch 的实现取舍 |
|---|---|---|
| [Recce](https://github.com/DataRecce/recce)、[SQLMesh](https://github.com/SQLMesh/sqlmesh) | schema、行数、有效业务键上的数据变化；执行后审计 | 实现目标表的小快照和逐键差异，保留构建来源；继续使用 DuckDB，不迁移整个平台 |
| [dbt](https://github.com/dbt-labs/dbt-core)、[Elementary](https://github.com/elementary-data/elementary) | 返回违规记录的规则、可追溯指标 | 展示可见规则前后状态；当前没有时间序列监控和告警服务 |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent)、[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)、[OpenHands SDK](https://github.com/OpenHands/software-agent-sdk) | 提交审阅、有界执行、卡住后的反馈与退出 | 一次预算内候选复核；长时间未产生补丁时进入收尾阶段；继续保留受限 SQL 工具 |
| [WrenAI](https://github.com/Canner/WrenAI)、[DB-GPT](https://github.com/eosphoros-ai/DB-GPT)、[Vanna](https://github.com/vanna-ai/vanna) | 相关业务上下文、可执行 SQL 与结果交付 | 工单与 README 优先、目标模型上下文和数据证据；不新增向量库／BI 平台依赖 |
| [Harbor](https://github.com/harbor-framework/harbor)、[Inspect](https://github.com/UKGovernmentBEIS/inspect_ai) | trial、异常、评分与版本分离 | 离线核验任务矩阵、逐次结果、计数、汇总和源码归档；历史修订单独保留 |
| [ADE-bench](https://github.com/dbt-labs/ade-bench)、[data-eng-bench](https://github.com/Snowflake-Labs/data-eng-bench) | 对真实物化关系验收，以整题为成功单位 | 独立 Oracle 与原始公开 verifier；部分组件通过仍算整题失败 |

没有在同一数据和预算上与这些系统比赛，本文比较的是机制与适配性。

## 第一版验收基线

- 14 项真实 dbt fixture 验收测试，加 21 项 Agent／服务／工具／API 等测试，均通过。
- 六个合成 holdout 任务的 v2 smoke：**6/6**，214,452 Tokens，估算 $0.071045。
- v1 正式对照：六题 × 三模式 × 三次，共 **54 次**；ReAct 18/18，Context 17/18，Verified 17/18。Context 的一次 Windows 持久化故障计入分母；原始和修订评分分别保留。
- 两道公开开发题：v1、v2 均 **0/2**。v2 Tokens 从 1,672,068 降到 533,419，减少 68.1%，业务语义问题仍存在。

这些结果不支持“Verified 一定更强”。合成 holdout 改变数据而保留问题语义；公开任务已经用于开发迭代。

## 第一轮：代码变化对应哪些数据变化

实现 `evidence.py`，服务在 Agent 前后采集目标表，网页新增「数据变化」。包括 schema、行数、明确声明且有效的业务键、增删改数量、有限样本和规则前后状态。

键重复／NULL、基线缺失、快照超过 5,000 行时，报告不能做可靠全量逐键对比。最终构建失败时提示数据可能陈旧。变化本身不作为正确性分数。

**验收通过：** 7 项实际 DuckDB 证据测试；两道真实 DeepSeek 回归 **2/2**。退款由 16→21 行，新增 5 条、改变 3 条；LTV 由 0→10 行。桌面与 390px 手机实际浏览器验收通过，0 JS 错误、0 非 GET 请求，旧记录正确显示未记录证据。

记录：[第一轮真实评测](../results/round1_evidence_20261025.json)、[证据接口](EVIDENCE.md)、[实际界面](screenshots/workbench-evidence.png)。

## 第二轮：预算内的候选语义复核

`review.py` 使用同一模型的独立上下文，对工单、README、原始 SQL 与候选补丁复核；不读取最终验收。复核计入同一最大调用数，最多一次，剩余预算供执行器核查。复核意见及补丁是否在其后改变均保存。

第一次验收暴露了回归：合成 **5/6**，一个正确增量补丁被缺少完整 README 的复核误导，添加了未要求的 watermark，并引用不存在的列。公开题仍 **0/2**，一个没有补丁，一个最后一步才写入，均未触发复核。原始记录保留，没有把这次尝试算作通过。

修订措施：未定位目标时也保留 README；finding 必须引用真实可见要求或原始 SQL；明确性能建议不能升级为业务要求。长时间只有探索且预算仅余六次时，暂收起只读探索工具，要求提交候选或说明阻塞；写入后恢复验证工具。复核上下文过大则明确跳过，格式错误或无据要求记为不确定。

**修订版验收通过：** 15 项上下文／复核／预算反馈测试通过；六道合成 holdout **6/6**，52 次模型调用、89 次工具调用、191,325 Tokens，估算 $0.063835，平均 96.59 秒。

公开同题重测仍 **0/2**（12/13、14/15 组件），563,985 Tokens，估算 $0.182636。两题确实各复核一次，随后补丁又改变，最终候选没有再次复核；NULL 排名总体和额外过滤仍有错误。功能回归恢复了，没有证据支持公开任务成功率提升。结果分别保存在 [修订前](../results/round2_semantic_review_20261025.json)、[修订后](../results/round2b_contract_review_20261025.json)、[公开重测](../results/public_native_v31_20261025.json)。

## 第三轮：离线核验报告与交付评分

正式 `audit.py` 检查缺失／重复 trial、状态与构建假通过、Token 加和、负费用、汇总重算、公开 verifier 与 reward、归档源码及 manifest。它只读已有结果，无模型调用，不修改输入报告。

预审计实际检出了修订前历史报告的一条“流程失败却标为通过”；正式报告已修订并保留原件。服务现在也会在验收后持久化失败时撤销交付通过状态，统计层额外要求流程完成、最终构建成功。补充修复了 `Path` 参数被误当成盘符根目录的上下文接口问题。

**软件回归通过：** 最终 63 项 Agent／上下文／工具／服务／网页／证据／复核／审计测试通过，其中审计 24 项，涵盖篡改报告、假通过、丢失 trial 和源码归档差异。早期 14 项真实 dbt fixture 测试已通过；数据生成、Oracle 和重放逻辑在本轮未改变。依赖检查无冲突。最终真实 API smoke 与封存审计记录在交付验收表中。

## 结果与复现边界

每次真实实验分别保存协议、失败与源码摘要，后续实验另存源码归档；早期缺失归档由审计明确标注。源码版本与评分修订分开记录。费用按配置单价估算，实际账单可能因缓存折扣不同。当前已实测 Windows 本机运行、网页与独立验收；Docker 配置随项目交付，但本机没有 Docker，未作容器实测。

最终 API 功能验收 **2/2**；本地和导出版本各 10 份报告、1,463 项审计检查，均无 error。完整测试、界面和历史 warning 见 [交付验收表](ACCEPTANCE.md)。

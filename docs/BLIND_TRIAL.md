# 一道未研究公开任务的单次原工单试跑

2026-10-26，固定 DataPatch v4.4 核心后，首次尝试 `dbt-carrier-delivery-performance`。**独立目标构建通过，原评测 16/16 个组件通过，整题 reward=1.0。** 仅运行一次 Agent，没有失败后重抽、补提示或再次付费尝试。

| 项目 | 实际记录 |
|---|---|
| 原任务 | [Snowflake-Labs/data-eng-bench，固定 commit](https://github.com/Snowflake-Labs/data-eng-bench/tree/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-carrier-delivery-performance) |
| 模型 | `deepseek-flash`；未使用 Pro |
| Agent 运行 | 1 次，模式 `verified`，上限 10 次模型调用、估算 $0.08 |
| 实际模型调用 | **7 次**，包括自身的候选审查 |
| 实际工具调用 | 11 次 |
| Tokens | 127,925：输入 108,120，输出 19,805 |
| 估算费用 | **$0.056202**；按项目配置单价计算，实际账单以服务商为准 |
| Agent 耗时 | 139.078 秒；不含准备和独立验收 |
| 停止原因 | `cost_limit`；下一次请求前触发保守预算保护，未自动重试 |
| 独立验收 | 目标 `dbt build` 成功；原 pytest **1 passed，16/16 组件**，无失败组件 |
| 核心版本 | `v4.4-session-consistency`，与此前交付相同 |

## “无辅助”在本次的含义

Agent 只接收原工单、原缺陷 SQL、既有 dbt 项目和数据库。保留产品原有的上下文构建、工具、自审和预算控制；没有人为添加业务检查、正确 SQL、测试断言或中途修复提示。`public_contracts=null`，`checks` 为空。

先删除准备阶段生成的旧正确目标视图，再清空新工作区的 `target` 和 `logs`，运行一次原缺陷模型作为初始状态。输入 SQL 哈希与上游 overlay 一致。数据库为独立可写副本，原始输入快照未修改。

Agent 于 **09:37:01 UTC** 停止；原测试文件在 **09:38:12–13 UTC** 下载。随后按原测试的二元评分协议独立验收。仅做本地路径替换和事先声明的 UTC 会话设置，断言未改；原测试 Git blob 与固定 commit 的树元数据一致。

SQL 候选直接来自 Agent 最后一次 `write_model`。人没有在独立验收前修改候选；达到费用保护不表示模型已经给出完整交接陈述，因此保留 `cost_limit`，没有改写成“模型自主宣布完成”。

## 选题与结论范围

先取固定 commit 的 103 个任务路径元数据，排除此前执行或研究过的 14 个任务。按现有原生适配条件筛选“单个 SQL overlay、已有唯一目标模型、不需额外业务输入”的候选，得到 **2 题**，在未读候选说明、SQL 或测试正文前，以种子 `20261026` 单次抽取本题。没有重抽。

这是**已知公开项目中、对本项目开发过程未研究过的一道工单**。它不是 103 题的代表性随机评测，不是跨项目泛化评测，也无法证明模型预训练没见过公开题。运行采用 Windows/DuckDB 本地适配及已核验的本地 dbt_utils 缓存，并非官方 Docker/Harbor 成绩。

原测试检查构建、无 Inf/NaN、行覆盖、列与分类、全局分位、同组排名、效率与可靠性指标等 16 个组件。通过说明本次候选满足该数据和原测试；不把单题通过率表述为通用能力的成功率。

## 查看证据

- [完整报告](../results/unseen_blind_20261026.json) 与 [可读报告及原始输出](../results/unseen_blind_20261026.md)。
- [候选 SQL](../results/blind_20261026/candidate.sql)、[补丁](../results/blind_20261026/candidate.patch)、[原始调用和工具事件](../results/blind_20261026/events.jsonl)。
- [选题协议](../results/blind_20261026/unseen_blind_selection_20261026.json)、[调用前封存协议](../results/blind_20261026/unseen_blind_run_20261026.json)、[原测试抓取哈希与时间](../results/blind_20261026/verifier-fetch.json)。
- [原评测结果](../results/blind_20261026/verifier.json)、[原测试](../results/blind_20261026/test_outputs.original.py)、[原 harness](../results/blind_20261026/test.original.sh)。
- [被测源码 ZIP](../results/unseen_blind_20261026_source.zip)公开版包含 99 个文件和逐文件哈希。实验准备脚本另存于证据目录。[归档发布说明](EVALUATION_AUDIT.md#公开归档)

核心源码的 SHA-256 为 `49f2808e761b575163949c57e09a3b29be75a1b7aca39134269336990dad4beb`。公开版 ZIP 的 SHA-256 为 `2d84c99525b9924d1764e88bd234e78bc87422497859d8b11c33497ecc701419`。

此次新增适配与评分入口的定向回归：`pytest tests/test_public_adapter.py tests/test_public_fixes.py -q`，**64 passed**。未重复运行此前耗时较长的全量 dbt fixture，也没有额外调用模型。

## 面试时可以这样讲

“我把 Agent 核心冻结后，从此前没研究过、且符合现有运行环境的公开工单中抽了一题。只给原工单和项目，让 Agent 自己读代码、查数据、改 SQL。一次运行用了 7 次 Flash 调用，估算 0.0562 美元；预算保护停止后，才拿原测试做独立验收，16 个组件全部通过。这个结果是一次原工单验证，我不会把它说成对所有未知任务都有很高成功率。”

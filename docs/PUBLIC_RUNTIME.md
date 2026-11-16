# 公开任务运行配置与复现

2026-10-26：后续模型调用仅使用 **Flash**，启用 thinking、`reasoning_effort=high`。原v41两轮和后续商品契约辅助修复分别记录，费用见 [COSTS](COSTS.md)。新增四题与成品复验均不调用模型；下文两轮限制用于解释v41历史计划，不自动启动新调用。

## 零模型API的八题适配

现在固定支持八题，新增四题为时区、连续日报、结算日汇率与cohort留存。默认任务集合保持原四题，额外题须显式指定。已有的工作台回放直接读取记录，不需要数据库重建或API。

新机器下载八题允许输入（不下载解答/测试，约489MB数据库）：

```powershell
.venv/Scripts/python.exe scripts/fetch_public_benchmark.py --destination external/data-eng-bench-expanded --task dbt-fix-refund-reconciliation --task dbt-fix-division-by-zero --task dbt-fix-inventory-model --task dbt-fix-product-metrics --task dbt-fix-timezone-sales --task dbt-fix-daily-revenue --task dbt-exchange-rate-settlement-date --task cohort-retention-matrix
```

新增四题成品验收：

```powershell
.venv/Scripts/python.exe scripts/verify_public_fixes.py --snapshot external/data-eng-bench-expanded --case-root external/native-cases/my-expanded-check --output artifacts/acceptance/my-expanded-check.json --task dbt-fix-timezone-sales --task dbt-fix-daily-revenue --task dbt-exchange-rate-settlement-date --task cohort-retention-matrix --acceptance-policy upstream_harness --duckdb-timezone UTC
```

该命令不调用模型，保留真实的当前候选及祖先`dbt run`、额外`dbt build`、工作区外原pytest与源文件hash。`upstream_harness`按原题的物化和原pytest判定；时区题原数据的主键质量失败保留为`project_quality`，没有改成成功。默认`dbt_build`仍要求额外build通过。运行异常、物化失败和原pytest失败，在两种策略下都会拒绝验收。

`--duckdb-timezone UTC`是显式运行环境：dbt profile和独立pytest launcher使用相同时钟，原测试文本仅替换路径，另存launcher全文/SHA；默认不设置，保留旧报告行为。时区题在上游README也被标为对环境敏感、结果仅供参考，具体边界看 [八题说明](PUBLIC_EIGHT_TASKS.md)。

可选本地依赖：本机缓存位于`external/package-cache/dbt_utils-1.3.3`，`receipt.json`锁定234个文件，并保留成功`dbt deps`日志、原包声明和lock。`integrations/public_packages.py::create_cache(source_project, deps_log, output)`可从一次已成功解析的同版本工程建立缓存；`validate_cache()`校验版本与所有字节，`install_cache()`仅修改新案例的运行副本，把同一库声明为本地路径，原配置另存`preparation/`。它不替换模型SQL或测试。

重现最后一次cohort补验时，在上述验收命令仅选择`--task cohort-retention-matrix`并加`--packages-cache external/package-cache/dbt_utils-1.3.3`，case/output使用新名字。原new4首验因registry连接重置为3/4，补验1/1，不能覆写首验或宣称一次四题全过。缓存的[原始receipt](../results/validation/package-cache/receipt.json)可独立核验；默认不传缓存时仍走原依赖解析流程。

本机C盘空间有限，开发与fresh成品案例位于`D:\DataPatch-work\`；源代码、报告与归档仍在本仓库。复现目录可自选，每题需要一份可写数据库，不要让多个案例共用同一可写DB。报告和case默认拒绝覆盖，用新名字开始，历史失败保持原样。

## 配置变化

| 项目 | 历史 Flash 公开运行 | 当前 Flash 配置 |
| --- | --- | --- |
| 请求模型 | Flash 系列，实际版本见原始事件 | `deepseek-flash` |
| thinking | `disabled` | `enabled` |
| reasoning_effort | 未启用 | `high` |
| max_tokens | 3,000 | 8,192 |

历史已检查事件中，单次最大输出为 **1,884 tokens**，未达到 3,000；历史失败没有输出截断的证据。当前每请求 8,192 是思考与回答合计输出上限，不是已经消耗的 token 数，也不是成功保证。

参数含义和工具调用的多轮要求见 [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。带 tools 的连续请求完整回传模型消息中的 `reasoning_content`；项目只在请求会话内保留它，不写入 events 或工作台。事件保留公开回答、工具调用、finish_reason、用量与响应标识。

## 用量与估算

Flash 保守按每百万输入 **$0.30**、每百万输出 **$1.20** 估算，采用高峰时段、输入缓存未命中口径；实际扣费可能受缓存和时段影响。价格核验于 2026-10-25，复现时可查 [官方价格表](https://api-docs.deepseek.com/quick_start/pricing/)。

`estimated_cost_usd = (prompt_tokens × 0.30 + completion_tokens × 1.20) / 1_000_000`。

推理 token 已计入服务端 `completion_tokens`，不再把明细中的 reasoning tokens 加一次。历史报告保留各自计价配置，新旧费用不混算。具体美元上限与费用控制以本轮冻结配置、实际记录为准。

## v41历史固定四题与执行边界

预登记：退款对账、客户除零、库存模型、新建产品指标四题，分别对应 `dbt-fix-refund-reconciliation`、`dbt-fix-division-by-zero`、`dbt-fix-inventory-model`、`dbt-fix-product-metrics`。

当前统一使用 `verified`，每任务最多 **12 次成功生成请求**；候选审阅包含在该上限内，HTTP 失败另行记录，网络超时与 HTTP 错误均不自动重试。每题重新准备独立 workspace，源码 zip、manifest、实际模型版本及参数绑定本次报告。整个后续公开验收最多两轮，不自动追加第三轮。

Agent 结束后再运行隔离的原版 pytest 验收；验收反馈不用于同次补丁继续修复。这里采用 Windows native adapted 执行口径，具体范围见 [公开任务说明](PUBLIC_BENCHMARK.md) 与 [四题登记](PUBLIC_EXPANSION.md)。

两轮已实际完成：首轮四题 3/4；第二轮只商品 0/1（8/11）。合计 55 次 Flash 调用，保守估算 $0.397302；不再新增模型轮次。详见 [完整验收](ACCEPTANCE.md) 与 [结果](RESULTS.md)。预算预停止现通过 `BudgetExceeded` 记录为 `cost_limit`，保留已有补丁，再由独立构建和业务验收判断；预期停止不自动带来任务成功。首轮旧异常判定和所有失败保持原样。

## 历史中断配置

曾登记 Pro thinking high、16,384 输出上限、24 calls、每题 $0.60，按输入 $1.32／输出 $3.96 每百万 tokens 估算；四题因账户余额不足 HTTP 402 中断，记录已保留。该配置仅用于解释历史复现记录，后续不再运行 Pro，24 calls／$0.60 不作为当前建议。

## 本机复现一题

在项目根目录使用已配置 API key 的环境。下面创建独立案例目录，`evaluate` 仅在 `run` 返回后执行：

```powershell
$env:DEEPSEEK_MODEL = 'deepseek-flash'
$env:DEEPSEEK_THINKING = 'enabled'
$env:DEEPSEEK_REASONING_EFFORT = 'high'
$env:DATAPATCH_MAX_OUTPUT_TOKENS = '8192'
$env:DATAPATCH_MAX_STEPS = '12'
$casePath = 'external/native-cases/product-flash-' + [guid]::NewGuid().ToString('N')
& '.venv/Scripts/python.exe' 'integrations/harbor_agent.py' 'prepare' '--case' $casePath '--task' 'dbt-fix-product-metrics'
& '.venv/Scripts/python.exe' 'integrations/harbor_agent.py' 'run' '--case' $casePath '--mode' 'verified' '--max-steps' '12'
& '.venv/Scripts/python.exe' 'integrations/harbor_agent.py' 'evaluate' '--case' $casePath
```

读码顺序：`config.py` 选择参数与价格，`provider.py` 构造请求并读取 usage，`agent.py` 保留多轮消息与调用预算，`context.py` 区分修复已有模型和创建缺失输出。新建任务只预载少量公开相关源 SQL、refs 与 schema，确认输入后创建目标，避免反复查找尚不存在的文件。

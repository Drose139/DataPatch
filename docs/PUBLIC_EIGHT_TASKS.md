# 八个固定公开工程：补丁与验收口径

本次在原四题之外增加时区、连续日报、结算日汇率和 cohort 留存四题。它们仍是固定的 `Snowflake-Labs/data-eng-bench` 公开开发案例，上游固定 commit 为 `a3278ad102829a6084dde086244a0ef665a8011c`，不是未知测试集或官方 Harbor 榜单。

这里记录的是 **`operator_reviewed` 成品 SQL 和实际执行证据**。新四题的编写、物化与原 pytest 验收没有调用项目的 DeepSeek 生成 API；补丁由助手辅助审阅开发，不表示用户已独立手写完成，也不表示 Agent 自主解决八题。历史 Flash 首轮 3/4、商品后续失败、v4.3 显式项目契约辅助修复分别保留在 [RESULTS](RESULTS.md)。

## 任务与目前已结束的证据

下表列出逐题已完成的证据，开发失败与 fresh 验收分别保留。最终包含 **9 次成品验收尝试、8 个不同任务，8 个任务最终通过**：原四题独立复验 4/4，新增四题首次 fresh 为 3/4，cohort 的基础设施补验另为 1/1。这不是一次统一的 8/8，也不是 9 次尝试全部通过，更不是 Agent 自主八题成绩。

| 任务 | 模型路径 | 已有真实证据 |
|---|---|---|
| `dbt-fix-refund-reconciliation` | `models/marts/sales/rpt_return_reconciliation.sql` | 原成品验收 13/13 组件，独立 build 通过 |
| `dbt-fix-division-by-zero` | `models/marts/customer/rpt_customer_metrics.sql` | 原成品验收 15/15 组件，独立 build 通过 |
| `dbt-fix-inventory-model` | `models/marts/inventory/rpt_product_inventory_metrics.sql` | 原成品验收 12/12 组件，独立 build 通过 |
| `dbt-fix-product-metrics` | `models/marts/product/fct_product_metrics.sql` | 原成品验收 pytest 11/11，独立 build 通过 |
| `dbt-fix-timezone-sales` | `models/intermediate/sales/int_sales__orders_enriched.sql` | 开发 05 与首次 fresh 均原 pytest 10/10，显式 UTC／`upstream_harness`；额外项目键质量失败原样保留 |
| `dbt-fix-daily-revenue` | `models/marts/sales/rpt_order_daily_summary.sql` | 开发 001 与首次 fresh 均原 pytest 13/13 |
| `dbt-exchange-rate-settlement-date` | `models/marts/finance/fact_revenue.sql` | 开发 18/20 → 20/20；首次 fresh 原 pytest 20/20；原失败保留 |
| `cohort-retention-matrix` | `models/marts/marketing/cohort_retention_matrix.sql` | 开发 23/24 → 24/24；首次 fresh 因 dbt deps 网络失败，没有执行原 pytest；独立 fresh 补验原 pytest 24/24，物化及额外 build 通过，原失败保留 |

最终 fresh 证据分别为 [原四题严格复验 4/4](../results/acceptance/public_core_recheck_20261026.json)、[新增四题首次验收 3/4](../results/acceptance/public_expanded_fixes_20261026.json)、[cohort 独立基础设施补验 1/1](../results/acceptance/public_cohort_infra_retry_20261026.json)。八个任务的最终验收中，七个额外项目 build 通过；时区题的额外键质量失败仍保留，按下述上游物化与原 pytest 口径接受。SQL 在 [examples/public_fixes](../examples/public_fixes/README.md)，运行过程的本机原始证据在 `artifacts/acceptance/`；不能把这些零调用验收记录算成新增模型成功次数。

## 新四题修复了什么

### 时区与混合日期格式

[公开工单](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-fix-timezone-sales/instruction.md)要求 SAP 和 POS 时钟相差 5 小时，日期格式混有标准 SQL、美式、欧式、紧凑日期和 Unix 秒，美式必须先于欧式尝试。补丁 [dbt-fix-timezone-sales.sql](../examples/public_fixes/dbt-fix-timezone-sales.sql)保留视图、全部输出列、源行与金额；统一解析四个事件时间，再将 POS 前移 5 小时。

真实失败与修订：

- 开发 01 在模型中定义局部 Jinja 宏，dbt 编译无法解析该宏；原 pytest 10 errors。修订改为模型内字符串模板展开，未增加或修改 staging／macro 文件。
- 开发 02 能物化目标，原 pytest 9/10。强制将 Unix 秒转 UTC，普通日期字符串仍是无时区时钟，本机 `Asia/Shanghai` 下 SAP 比较差 8 小时。
- 开发 03 改为仓库会话时钟解析 Unix 秒，SAP 比较通过，但 39 条记录出现发货早于下单，原 pytest 仍为 9/10。同一个视图和源数据，仅在只读连接切换到 UTC，反序计数从 39 变为 0；这不是更改事实行或补造发货时间。
- 开发 04 不改 SQL 和源输入，显式将 dbt profile 与验收 runtime 设为 UTC；候选及祖先物化成功，额外 build 仍保留原键质量失败。下载原 verifier 时遇 SSL EOF，pytest 未执行，单列基础设施错误。
- 开发 05 仅重试独立原 pytest，不再运行 dbt 或改 SQL；原测试 10/10，0 failed／errors／skipped。验收采用 `upstream_harness`，引用 04 已保存的实际物化证据，并核对候选与 runtime 文件字节未变化。

原输入还保留 SAP 的 177 个空订单键以及源内重复／跨系统重复键；`dbt build` 的键质量检查因此失败。补丁没有为了变绿而去重、删除源行或编造键。目标物化成功、项目质量检查失败和原 pytest 判定分别保存。

[上游 README](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/README.md#tasks)已明确说明该题具有时区敏感和 DuckDB 执行顺序敏感性，单题结果应视为 advisory。此次 UTC runtime 适配在 profile、case 元数据和原 verifier 报告中显式记录，并为每个验收 DuckDB 连接设定 UTC；原测试只做路径翻译，独立 launcher 另存代码与 SHA。它不是已实测的官方容器结果，也不能消除上游注明的单题局限。

本机证据：`artifacts/acceptance/timezone-development-01/` 至 `timezone-development-05/`。03 的 `session_timezone_probe.json` 记录只读时区对照；04 保存 runtime 文件前后原字节、成功物化、失败的额外质量检查与下载错误；05 保存实际 10/10 原 pytest 和来源。成品 SQL SHA-256 为 `6b31024ac3a6607b96478910246cdaf922030202f761011692adbe17c2cae328`。

### 连续日报与累计收入

[公开工单](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-fix-daily-revenue/instruction.md)要求日期范围没有缺口、结果完整和累计收入正确。补丁 [dbt-fix-daily-revenue.sql](../examples/public_fixes/dbt-fix-daily-revenue.sql)先按日期聚合原订单，再连接最早到最晚订单日的完整日历，空日填零，最后用明确的逐行窗口累计收入；保留原金额列与物化方式，不修改 staging。

开发 001 的原 pytest 为 13/13。原始报告在 `artifacts/acceptance/daily-development-001/verifiers/dbt-fix-daily-revenue/daily-evaluation.json`，这是已经结束的单题开发验收，不替代统一新案例验收。

### 结算日汇率与粒度取舍

[公开工单](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-exchange-rate-settlement-date/instruction.md)要求按最近付款结算日选择汇率，无付款时回退订单日，USD 金额保持不变，并增加结算日、汇率和两列 USD 金额。补丁 [dbt-exchange-rate-settlement-date.sql](../examples/public_fixes/dbt-exchange-rate-settlement-date.sql)先按订单归并最近付款时间，避免多笔付款放大事实，再选择结算日对应汇率；缺失日优先回溯已有历史日，无历史时再考虑未来已有日，最终兜底策略在 SQL 中可审阅。

工单同时要求保留原粒度，却需要为原日／币种／来源聚合内不同订单表达不同结算日和单一汇率。开发 001 采用聚合组的最大结算日、保留三个键，原 pytest 18/20；开发 002 保留三个原维度，并按新增结算日细分，原 pytest 20/20。应说明这是依据原验收要求作出的公开开发修订，不能声称 SQL 完全没有改变原分组粒度，或这是未受验收反馈辅助的盲测结果。

两次原始报告分别在 `artifacts/acceptance/fx-development-001/` 与 `fx-development-002/`，不会用第二次通过覆盖第一次失败。

### Cohort 留存与客户级累计去重

[公开工单](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/cohort-retention-matrix/instruction.md)要求按注册月定义 cohort，包含从未下单客户，按精确日历月统计留存，只纳入指定有效订单，累计客户不能重复计数。补丁 [cohort-retention-matrix.sql](../examples/public_fixes/cohort-retention-matrix.sql)保留客户群体，先得到客户级有效订单与月份指标，再聚合渠道／cohort；配置 `marketing_analytics`，实际数据库 schema 为 `main_marketing_analytics`。

开发 001 的原 pytest 为 23/24，early churn 的口径在存在注册前有效订单时与原验收不一致。开发 002 明确要求客户最早和最晚有效月份偏移都为 0，原 pytest 24/24；未硬编码客户或 cohort ID，记录 `development_feedback_used=true`。这属于验收后的公开开发修订。

两次结果为 `artifacts/acceptance/cohort-development-001.json` 和 `cohort-development-002.json`；开发时的只读数据预览不计作 pytest 成绩。

新增四题首次 fresh 批次的 cohort 在 `dbt deps` 阶段遇连接重置，退出码 2，准备未完成，原 pytest 未执行。这份失败保存在 `artifacts/acceptance/public_expanded_fixes_20261026.json` 及 case 的 `preparation/deps.json`，没有被补验覆盖。

后续在新案例中仅补验 cohort，报告 [public_cohort_infra_retry_20261026.json](../results/acceptance/public_cohort_infra_retry_20261026.json) 记录实际物化、额外 build 与原 pytest 24/24 均通过。为避开依赖下载故障，runtime 使用同版本 `dbt_utils 1.3.3` 本机缓存，234 个文件逐一核对 SHA-256；原 `packages.yml`、锁文件、cache receipt、替换后的本机依赖配置及各自 SHA 一并存档。这里只改变依赖取得方式，不改 SQL、源数据或原测试断言；显式 UTC 设置继续保留。它是有记录的环境补验，不应改写原批次的 3/4。

## 原测试、物化与项目质量检查分开

原四题成品使用 `dbt_build` 门槛：额外目标 build 成功且原 pytest／组件验收通过。新增题对照其 pinned 上游 `test.sh`，采用显式 `upstream_harness` 口径：当前候选及祖先实际物化、目标节点成功、原 pytest 有效执行且完全通过；额外项目 `dbt build` 的结果仍原样保留在 `project_quality`，不会将其中的失败改成成功。

这两种策略不应混成同一套严格度相同的成绩。`verification` 保存策略与必需条件，`dependency_build` 保存实际物化，`build` 保存额外质量检查；时区 runtime 参数也应随协议记录。上游原测试由独立评估器在 case 外执行，补丁编写时不打开测试或参考解，验收后仅查看真实执行日志以说明开发修订。

v4.4 已补齐 UTC 会话一致性：`Workspace` 的查询／schema 工具、上下文的 schema／关系剖析都接收显式 `None/UTC`，native 与已审阅验收从 case 元数据透传；默认 `None` 保留原行为。实际实现见 [workspace.py](../src/datapatch/workspace.py)、[context.py](../src/datapatch/context.py)、[harbor_agent.py](../integrations/harbor_agent.py)，真实 DuckDB epoch 转换、查询与上下文一致性、只读保护测试见 [test_session_consistency.py](../tests/test_session_consistency.py)；相关目标测试已通过，未增加模型调用，不追改 v4.3 记录。

当前扩展验证的是 SQL 成品与公开适配流程，尚未给核心网页 Agent 新做八题统一自主回归。实现 UTC 传递和软件回归通过，不等于已完成新的模型效果试验。演示来源、已审阅补丁与真实模型工具轨迹继续分别显示；Docker、Snowflake 和官方 Harbor 全量运行未因此获得实测证明。

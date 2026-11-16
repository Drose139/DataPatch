# 公开任务扩展预登记

本轮在运行新任务前固定增加两题，并保留此前两题的全部失败记录。上游锁定为 `Snowflake-Labs/data-eng-bench` 的 `a3278ad102829a6084dde086244a0ef665a8011c`，数据库继续使用已有 LFS SHA-256 校验副本。以下选择只依据任务说明、任务输入及环境设置；未读取新题 solution 或 verifier 内容，也未调用模型。

| 新任务 | 模型路径 | 任务形态与覆盖的业务语义 |
|---|---|---|
| `dbt-fix-inventory-model` | `models/marts/inventory/rpt_product_inventory_metrics.sql` | 修复现有库存指标：产品覆盖、零除、库存健康分层与速度评分；滚动窗口以 `MAX(transaction_date)` 为参考时间。 |
| `dbt-fix-product-metrics` | `models/marts/product/fct_product_metrics.sql` | 创建商品业绩汇总：商品与变体、订单和订单行的粒度，全部商品覆盖、明确订单状态过滤、加权均价与防止连接放大。 |

库存题的 buggy SQL 来自 `environment/data/rpt_product_inventory_metrics.sql`。商品汇总题的目标文件在基础项目中不存在，任务环境也不注入 buggy SQL；适配器应保留这种“创建模型”的原始形态，不伪造已有文件或复制答案。

两题说明与输入的一手来源：

- [库存任务说明](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-fix-inventory-model/instruction.md)、[库存 buggy SQL](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-fix-inventory-model/environment/data/rpt_product_inventory_metrics.sql)。
- [商品汇总任务说明](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-fix-product-metrics/instruction.md)、[原始任务环境](https://github.com/Snowflake-Labs/data-eng-bench/blob/a3278ad102829a6084dde086244a0ef665a8011c/tasks/dbt-fix-product-metrics/environment/Dockerfile)。

选择理由是增加库存运营和商品销售聚合两种任务，避免只重复原退款/客户评分题。商品汇总的输出列、状态过滤和加权平均定义明确；库存题明确要求固定数据参考日，未选择已知 timezone 风险题。备选 `dbt-fix-inventory-balance` 额外要求创建 YAML 测试，超出现有仅写 SQL 的工具边界；`dbt-fix-category-revenue` 的说明没有明确细化业务口径，因此本轮不选。

只根据 Git tree 元数据确认两题均存在 `tests/test_outputs.py`：库存 verifier blob 为 `a98890943f01dccb7d386097b45045aa9a24a84d`，商品汇总为 `546dbf289c0df3aa3a06d54db683e90ca50407d3`。这只能证明路径存在，不能提前证明 verifier 可靠或任务能通过；待各次 Agent 停止后，才在独立目录下载并执行原始 pytest。原断言只允许路径适配，不能改评分逻辑。

## 适配范围

仅修改 `scripts/fetch_public_benchmark.py`、`integrations/harbor_agent.py` 和其测试，不修改 Agent、provider 或核心执行策略。

- fetch 对固定四题支持可配置子集；默认仍为历史两题，避免旧命令改变计划范围。缓存数据库须核验原 hash，无需重复下载 489 MB。
- 库存题复用“初始化祖先，再覆盖 buggy SQL”流程。
- 商品汇总题先初始化任务说明所列的四个 staging 模型及祖先：`stg_orders__order_lines`、`stg_orders__orders`、`stg_product__product_variants`、`stg_product__products`。目标 SQL 保持缺失，交给 Agent 创建。
- report 显式记录计划任务子集与重复编号。旧报告仍按原两题协议读取；不因支持四题而回改历史报告。
- 每次模型执行使用全新 workspace。模型停止后单独执行原 pytest；通过要求实际测试执行、二元 reward=1、退出码 0，且全部组件通过。

本阶段只登记和实现适配，不运行模型。后续四题成绩及重复确认必须依据实际执行填写；这是固定公开开发子集，不能标作未知保留集或官方 Harbor 成绩。

## v4 首轮四题固定计划

| 任务 | 全新 case |
|---|---|
| `dbt-fix-refund-reconciliation` | `external/native-cases/refund-v4-01` |
| `dbt-fix-division-by-zero` | `external/native-cases/division-v4-01` |
| `dbt-fix-inventory-model` | `external/native-cases/inventory-v4-01` |
| `dbt-fix-product-metrics` | `external/native-cases/product-v4-01` |

四题统一 `verified`、24 次模型调用上限、每次运行估算预算 0.60 USD，首轮四次运行合计估算上限 2.40 USD。模型计划为 `deepseek-v4-pro`，thinking enabled、reasoning effort high、最大输出 16,384 tokens；实际返回模型版本、用量与计价参数按本次运行原始事件及配置记录，不能沿用旧 Flash 指标。冻结后的源码 zip 与 core digest 在实际运行报告中绑定。

fetch 已支持 `--task` 重复传入固定子集。report 使用 `--planned-task` 重复明确这四题；省略该参数仍沿用历史两题。独立重复确认必须预先指定新的输出和 `--repeats`，通过 `--repeat` 记录从 0 开始的重复编号，不能把事后追加当成原来预登记的重复实验。

## 首轮中断与适配修订

用户随后明确禁止 Pro，要求全部使用 Flash，最多再做一两轮，不做多模式对照。上述 v4 计划仅作为历史中断记录保留。当前 v4.1 采用 `deepseek-flash`、thinking high、8192 输出上限、每题 12 次调用（包含复核），每题估算上限 $0.125，四题每轮合计 $0.50，最多两轮 $1.00；下一次请求发送前保守预留输入与输出预算，不自动重试付费请求。先顺序执行一轮，只有必要修复才执行第二轮，并单独保留两轮结果。

v4 首轮四题均因模型 API HTTP 402（账户余额不足）中断。四个记录保留失败状态与固定分母，不能把未完成的 0/4 当作完整执行后的模型正确率。初稿保留为 `public_native_v4_20261025_unamended.json`；没有根据后验业务验收结果修改提交或重跑模型。

原商品汇总 verifier 使用普通 pytest 测试与 shell `test.sh`，不写组件型 `reward.json`。适配器在独立评估目录保存原 shell 与 hash，按原 harness 的二元规则判定：pytest 退出码 0、至少一个通过测试，并且无失败、错误或跳过。原断言不变，记录 `grading_protocol=pytest_exit_status`、四类测试计数和评分来源；组件型题继续使用原组件/reward 方式。

新版本的交付 build 只选择目标模型。祖先已在准备阶段构建，这与上游目标级运行一致，避免把原项目中不属于本工单的上游数据质量测试带入交付门槛。同时要求 manifest/实际 run results 中存在目标模型的成功节点；dbt 退出码 0 但目标缺失或无节点不算成功。旧版本的原始 build 证据保持原样，不补称旧 no-op 已成功构建目标。异常退出也在 `finally` 中记录实际墙钟耗时，后续不会把缺失耗时默认值当真实 0 秒。

## 验收文件指纹口径修正

v4.1 Flash 首轮的 `adapted_sha256` 计算对象为 UTF-8 编码的 LF 规范化适配文本；当时 Windows `write_text` 将实际文件写成 CRLF，因此它不是实际落盘文件的字节 hash。四题文件转换回 LF 后均与记录值一致，原始上游文件的字节 hash 也一致；测试断言和任务评分未变。历史报告原样保留。后续适配器改用 `write_bytes(adapted.encode('utf-8'))`，并以本项目测试核对实际文件字节 hash，保证后续记录与落盘文件一致；没有为此重跑上游验收或模型。

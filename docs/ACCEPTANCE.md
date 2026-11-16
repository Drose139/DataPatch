# 交付验收记录

## 最终八题成品与软件验收

八个不同固定公开任务的成品已全部取得通过结果。三份全新案例报告分别为[原四题4/4](../results/acceptance/public_core_recheck_20261026.json)、[新增四题首验3/4](../results/acceptance/public_expanded_fixes_20261026.json)、[cohort依赖修复补验1/1](../results/acceptance/public_cohort_infra_retry_20261026.json)。共9次尝试，8次通过；原cohort因dbt registry连接重置未执行，随后相同SQL、原数据和原测试，仅用校验后的本地同版本依赖补验，旧失败未覆盖。这是8个不同题的最终成品覆盖，不能称一次未经辅助的Agent八题8/8。

| 公开题 | 原始验收 | 额外目标dbt build |
|---|---|---|
| 商品 | 11/11 pytest | 通过 |
| 退款 | 13/13组件，1个pytest函数 | 通过 |
| 客户 | 15/15组件，1个pytest函数 | 通过 |
| 库存 | 12/12组件，1个pytest函数 | 通过 |
| 时区 | 10/10 pytest，显式UTC | 原输入177空键/1308重复组导致失败，原样保留为quality诊断 |
| 连续日报 | 13/13 pytest | 通过 |
| 结算日汇率 | 20/20 pytest | 通过 |
| Cohort留存 | 24/24 pytest | 通过 |

实际原pytest函数共81个通过，退款/客户/库存另有40个组件；两种计数不混合。原四题要求额外build通过，新增四题采用预登记`upstream_harness`，要求真实当前候选及祖先run、目标节点成功和原pytest全过。时区题上游自身标为环境敏感/advisory，不当作全量榜单或未知任务泛化证明。[逐题说明](PUBLIC_EIGHT_TASKS.md)保留业务口径歧义与开发失败。

最终软件测试：**222 passed、1条Starlette客户端弃用提示，45.65秒**；[原始记录](../results/validation/final_release_software_20261026.json)。另一次真实dbt fixture验收为**14 passed，754.23秒**，见[记录](../results/validation/fixture_recheck_20261026.json)，未把两次执行合成一次。依赖`pip check`无冲突。Edge桌面/390px真实服务12项只读检查通过，零页面错误、零非GET请求；[界面证据](../results/validation/public_eight_ui_20261026.json)。

本次修复包括孤儿键证据/归属、可执行公开契约的NULL漏检、新ref依赖物化、原协议与附加quality分离、显式UTC贯通工具与验证器、依赖包哈希缓存，以及准备失败的诚实回放。当前核心`v4.4-session-consistency`，SHA `49f2808e761b575163949c57e09a3b29be75a1b7aca39134269336990dad4beb`；历史模型成绩继续绑定各自原始快照。新增公开题验收零模型API，商品真实Flash修复费用单列在下节。 [最终源码归档](../results/release_v44_20261026_source.zip)与[独立八题审计](../results/validation/public_eight_release_20261026.json)供复核；审计同时确认历史失败、原测试、依赖receipt和源码归档边界。

## 2026-10-26：修复后实际验收

四份 `operator_reviewed` 成品补丁在全新隔离案例中完成原始公开验收：**商品11/11、退款13/13、客户15/15、库存12/12，整题4/4**。执行使用原始项目、校验后的原始数据库、真实目标 build 及工作区外上游 pytest；未调用模型 API。该结果属于成品补丁验收，独立于自主 Agent 成绩。[完整报告](../results/acceptance/public_fixes_20261026.json) · [可审阅 SQL](../examples/public_fixes/README.md)。

Agent 定点确认与修复另记：v42 未辅助候选为7/11，12次Flash、估算$0.076260；v43从该失败候选出发，加入明确的项目公开业务契约，4次Flash、62,455 Tokens、估算$0.021761，**独立目标构建及原始11/11通过**。v43结束为`step_limit`，不伪造口头交付或模型已自验；没有向模型提供正确SQL或最终测试。两次合计估算**$0.098021**，低于预登记的$0.125上限。[失败记录](../results/v42_relationship_product_20261026.json) · [契约辅助修复](../results/v43_contract_repair_20261026.json) · [契约说明与反例](PUBLIC_CONTRACTS.md)。

此处最初的软件回归为149项，最终222项见页首；历史运行保留各自源码。成品回放通过桌面和390px手机真实Edge检查，零页面错误、零非GET请求。历史模型失败、费用、源码与原始测试记录均保留。

## 历史公开工程扩展：v41 两轮 Flash 验收

本次按用户要求仅使用 Flash，不做多模式对照。首轮固定四题 **3/4**；第二轮只补测商品汇总，**0/1**，由 7/11 改善为 8/11，仍未通过。退款、客户、库存各有一次原始验收通过记录；商品未补齐，不能写成四题全部通过。没有第三轮模型调用。[剩余差异诊断](PUBLIC_REMAINING_ISSUE.md)用只读 SQL 证明：12 条孤儿产品键可通过唯一变体关系回到现有产品，合计 20 件销量、2,482.8968 收入，恰好等于差额；只读诊断没有修改模型或产生新验收分数。

| 轮次 | 任务 | 上游原始验收 | 整题 | 调用 | 估算费用 | 停止原因 |
|---|---|---|---|---:|---:|---|
| 首轮 | dbt-fix-refund-reconciliation | 13/13 components | 通过 | 12 | $0.069870 | model_finished |
| 首轮 | dbt-fix-division-by-zero | 15/15 components | 通过 | 12 | $0.091442 | step_limit |
| 首轮 | dbt-fix-inventory-model | 12/12 components | 通过 | 10 | $0.075023 | model_finished |
| 首轮 | dbt-fix-product-metrics | 7/11 tests | 未通过 | 10 | $0.092017 | ModelError |
| 第二轮，仅商品 | dbt-fix-product-metrics | 8/11 tests | 未通过 | 11 | $0.068950 | model_finished |

两轮合计 **55 次 Flash 调用、1,065,238 Tokens，保守估算 $0.397302**；这是峰时、输入全不命中缓存估算，实际账单以服务商为准。计划预算为首轮 $0.50 加第二轮单题 $0.125；没有重跑已经通过的三题。逐响应缓存费用重估见 [COSTS](COSTS.md)。

本次完成：缺失模型的通用输入发现、精确筛选与源金额核对提示、Flash-only 强制限制、请求前预算预留、预期 `cost_limit` 停止、普通 pytest 评分协议、目标模型真实构建门槛及公开真实回放。软件回归 **127 passed，1 warning，14.10 秒**；此前 14 项真实 dbt fixture 测试单独通过，本轮未改 fixture/oracle，不与 127 项合成一次执行。

[首轮完整结果](../results/v41_flash_round1_20261025.json) · [第二轮完整结果](../results/v41_flash_round2_20261025.json) · [读码与讲解](PUBLIC_PROJECT_GUIDE.md) · [费用](COSTS.md)。两份报告的离线审计分别 162 / 99 项检查，均 0 errors / 0 warnings；原始失败保留。全部 13 份正式报告本地及导出审计均 0 errors、5 个明确历史 warning，见 [完整导出审计](../results/validation/public_full_exported_20261025.json)。桌面和390px手机只读验收通过，0浏览器错误、0写请求，见 [第二轮界面记录](../results/validation/public_flash_round2_ui_20261025.json)。

最终核心源码摘要：`c645e44f1b2d31482928f703cd1fae78cd9d6cc29c37f0169e39de9074d18837`，对应 [第二轮源码归档](../results/v41_flash_round2_20261025_source.zip)。首轮三项成功绑定其先前独立版本，第二轮只验证商品，不能写成最终版本全四题复测。Native 环境与官方 Docker / Harbor 有差异，这是固定公开开发任务，不能宣称未知任务泛化或官方榜单成绩。

## 历史初版交付验收

日期：2026-10-25。项目：DataPatch。执行环境：Windows、Python 3.12.2、DuckDB 1.5.6、dbt-core 1.12.6、dbt-duckdb 1.11.0；依赖锁定在 `requirements.lock`。

| 验收对象 | 实际结果 | 证据 |
|---|---|---|
| 任务数据与独立 Oracle | 14 项真实 dbt fixture 测试通过；原始缺陷失败、参考修复逐行通过、源完整性及重复 delivery 验收 | `tests/test_fixtures.py`；本轮没有修改数据生成、Oracle 与重放语义 |
| 最终软件回归 | **63 passed**，7.42 秒；一条测试客户端弃用提示，无测试失败 | Agent、上下文、工具、API、服务、证据、复核和审计测试；其中 audit 24 项 |
| 最终依赖 | `pip check` 无冲突 | 当前 `.venv` 与 lock |
| 第一轮数据证据 | 7 项证据测试；真实回归 **2/2**；桌面及手机实际 UI 通过 | [第一轮报告](../results/round1_evidence_20261025.json)、[界面验收](../results/validation/round1_evidence_ui_20261025.json) |
| 第二轮复核，修订后 | 六道合成任务 **6/6**，191,325 Tokens，估算 $0.063835 | [实际报告](../results/round2b_contract_review_20261025.json)；修订前 5/6 原样保留 |
| 最终真实 API smoke | 同一退款 holdout：Baseline **1/1**、Verified **1/1**；Verified 包含一次实际候选复核 | [最终报告](../results/final_acceptance_20261025.json) |
| 正式结果审计 | 10 份报告、1,463 项检查；**0 errors**、4 个明确历史 warning；源报告未修改 | [本地产物审计](../results/validation/final_audit_20261025.json)、[导出结果审计](../results/validation/exported_audit_20261025.json) |
| 界面 | 本地真实服务、桌面与 390px 手机；只读浏览，不产生模型调用 | [最终 UI 验收](../results/validation/final_ui_20261025.json) |

最终 API smoke 的 Verified Run ID 为 `42fdb20f-0177-4f84-a529-f29b5b6803da`：8 次模型调用、12 次工具调用、20,401 Tokens，完整执行 85.48 秒，估算 $0.007141。Baseline Run ID 为 `dc4496b4-581d-4bc2-aeb4-313f1da328ef`，一次模型调用、1,722 Tokens，估算 $0.000777。它们是功能验收，不是对两种策略能力的统计比较。

最终核心源代码摘要：`dbb7416bebfbaabb4085801156464f372fdd3920b8c1c47e8776791246c377bc`。对应 [最终验收源码归档](../results/final_acceptance_20261025_source.zip)。各历史实验按各自冻结版本解释。

审计四项 warning：首次公开实验没有源码 zip；两份早期归档没有 manifest，但核心源码摘要绑定通过；未修订历史报告被明确排除。后续归档均核验逐文件哈希。审计通过表示记录和计算自洽，不改变业务通过率。

公开 data-eng-bench 的最终两题仍 **0/2**，组件为 12/13、14/15；退款窗口总体与额外状态过滤仍有业务错误。完整失败保存在结果中。当前没有 Docker，容器配置未作本机实测；已经实测的是本地可信 SQL 项目的执行与展示。

调研来源、三轮改进、失败和修订理由见 [IMPROVEMENTS.md](IMPROVEMENTS.md)。接手顺序见 [CODE_READING.md](CODE_READING.md)，面试讲法和简历 bullet 见 [INTERVIEW.md](INTERVIEW.md)。

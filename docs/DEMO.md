# DataPatch：3 分钟演示

演示优先回放已保存的真实记录。真实模型运行回放和已审阅补丁验收回放分别标注，页面读取原始记录，不重新生成回答或伪造模型事件。

公开工程的说明见 [PUBLIC_PROJECT_GUIDE.md](PUBLIC_PROJECT_GUIDE.md)，实际结果见 [RESULTS.md](RESULTS.md)。历史 Flash 首轮四题 3/4、商品第二轮 8/11 保留；已审阅成品另验收 4/4，商品原 pytest 11/11。随后 v4.2 通用剖析仍为 7/11；v4.3 从失败候选加入显式项目契约继续修复后 11/11，不是原工单无辅助盲测。新的付费执行仅限已授权协议，Flash-only，不为演示额外启动。

## 启动与准备

在项目根目录、已安装项目依赖的 Python 环境中执行：

```powershell
python -m datapatch.cli doctor
python -m datapatch.cli serve
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。Windows 终端未激活虚拟环境时，直接使用 `.\.venv\Scripts\python.exe -m datapatch.cli serve`。

`doctor` 只检查配置，不发起模型请求。模型 API 密钥在项目根目录 `.env` 配置，浏览器不需要填写密钥。当前后端为可信项目的本机执行，没有 Docker 隔离演示。

推荐公开 Agent 记录 `b0a054d0-8c8d-576f-9be4-f9445f271a3a`：v4.3 商品显式项目契约辅助继续修复，来自 `results/v43_contract_repair_20261026.json`。它实际使用 Flash，4 次调用、7 次工具调用、62,455 Tokens，估算 $0.021761；独立目标构建及原 pytest 11/11，停止原因 `step_limit`。开场须说明起点是 v4.2 的失败 AI 候选，契约来自 `project_configuration`。

若展示成品交付，使用 `bfd1ddf6-c4a0-56bd-9435-4003b3f1d570`：标签为“已审阅补丁验收回放 · 未调用模型”，商品 11/11；四题成品总验收在 `results/acceptance/public_fixes_20261026.json`。它没有模型事件、费用或数据快照，不能当作自主 Agent 成绩。合成退款 `42fdb20f-0177-4f84-a529-f29b5b6803da` 保留为数据变化与真实候选复核的备选演示。

原始产物位置：

```text
artifacts/runs/<run_id>/run.json
artifacts/runs/<run_id>/events.jsonl
artifacts/runs/<run_id>/patch.diff
artifacts/runs/<run_id>/verification.json
```

演示前查看该记录的 `provider`、`model`、`status` 和 `verification`。选择已完成、自己能解释的真实记录。它可以失败；失败案例也能展示验证如何发现问题。不要把单元测试里的 FakeClient 结果当成模型运行。

## 推荐：3 分钟公开工程回放

| 时间 | 屏幕操作 | 讲解要点 |
|---|---|---|
| 0:00–0:25 | 在「运行记录」打开 v4.3 商品记录 | “这是实际 Flash 的已记录回放；已有失败候选加显式项目契约继续修复，不是新题盲测。”指明 Run ID 和来源报告 |
| 0:25–0:55 | 在「运行数据」展示 `public_contracts`、`target_start` | 契约公开收入使用 `line_total`、有效销售事实保全及可信产品归属；原工单未被覆盖，起始 SQL 与契约文件有独立哈希 |
| 0:55–1:25 | 展开真实的 `read_file`、`query_sql`、`write_model` | 实际轨迹先读 README、工单和三份 SQL 检查，再查直接键／变体归属及源金额，最后写入模型。该次没有 `run_dbt`、`check_contracts` 或候选复核调用，不补讲不存在的模型动作 |
| 1:25–1:55 | 切到「代码变更」 | 展示真实差异，解释产品归属、独立聚合和源金额；少于 6 次调用跳过语义复核，四次预算内交付候选 |
| 1:55–2:25 | 切到「业务检查」与「运行数据」的 `final_build`、`raw_verifier` | 独立目标构建和原 pytest 11/11 是 Agent 停止后实际执行的。`step_limit` 与独立验收通过可同时成立；公开记录没有前后快照时明确展示缺失 |
| 2:25–3:00 | 展示 v4.2 失败报告，再打开商品成品回放 | v4.2 12 调用、7/11 的失败仍保留；v4.3 4 调用、11/11，两段估算共 $0.098021。成品回放清楚标为 `operator_reviewed`、未调用模型；四题成品 4/4 与自主首轮 3/4 分别陈述 |

v4.2 失败回放为 `2b00dac4-a0de-574a-a9ee-c2874180b528`，报告为 `results/v42_relationship_product_20261026.json`。v4.3 是一次有项目配置辅助的公开开发继续修复；不能据此声称未知任务泛化，或把先前三题与这次辅助结果合成统一无辅助四题成功率。

## 备选：历史合成退款回放

真实在线运行耗时取决于模型响应、工具步骤与 dbt 执行，不能保证在 3 分钟内结束。面试演示优先采用已完成记录，先说明回放来源；另准备现场启动入口，供对方验证。

| 时间 | 屏幕操作 | 讲解要点 |
|---|---|---|
| 0:00–0:20 | 显示工作台；打开「运行记录」 | “这是已保存的真实 DeepSeek 运行回放，页面读取原始事件；接下来不重新生成模型回答。”指出 Run ID、模型和模式 |
| 0:20–0:45 | 打开历史最终验收退款记录；展开任务上下文 | 合成零售工单要求每条源退款都保留，包括取消订单和零申请金额；修复前的订单关联与状态过滤漏掉退款，直接相除产生 NaN |
| 0:45–1:10 | 展开一次读取／查询，再展开写入与 dbt 执行 | 展示实际参数与返回，说明 Agent 先读契约和证据，再修改 SQL |
| 1:10–1:40 | 切到「代码变更」和「数据变化」 | 补丁移除未经契约要求的订单过滤，并对零分母返回 0；数据从 16 行变为 21 行，增加 5 条、内容变化 3 条 |
| 1:40–2:10 | 展开轨迹中的语义复核事件；必要时在「运行数据」查 `candidate_review` | 本次真实意见为 approve，引用 README 的完整退款覆盖与比例要求；`patch_changed_since_review=false`，但模型意见只作建议 |
| 2:10–2:35 | 切到「业务检查」 | 展示最终构建、所有行值、列和源数据完整性检查。通过依赖执行与独立验收，最终 Oracle 没有用于修复反馈 |
| 2:35–3:00 | 打开最终验收与历史公开 v3.1 报告 | 最终验收是退款单题的 baseline 与 verified 各一次，均通过；历史公开 v1～v3.1 两题各版均 0／2。最新四题另看 RESULTS，保留各版原结果 |

如果该记录没有模型修复重试，就不要声称这次展示了自动恢复。可另找真实出现“检查失败 → 继续修改 → 再验证”的记录；没有这样的记录时，说明代码具备反馈路径，是否改善效果还需实验。

推荐记录实际为 8 次模型调用（含一次复核）、12 次工具调用、20,401 Tokens，估算 0.007141 USD。`candidate_review` 保留候选摘要、意见与补丁摘要；本次复核后补丁未再变化。复核调用计入同一预算，approve 不能替代最终验收。

## 历史合成任务的现场启动入口

下面保留原合成任务的界面入口说明。当前公开工程演示使用已保存回放；新的公开执行沿本次已授权协议和 [PUBLIC_RUNTIME.md](PUBLIC_RUNTIME.md) 的配置约定进行，仅用 Flash，不为演示额外点击启动、重跑历史 54 次实验或新增多模式对照。v4.1 两轮限制对应其已封存协议，后续定点开发另存记录。

1. 左侧选任务；选择 `verified`，确认最大步数与模型配置。
2. 点击「启动修复」。每秒更新的轨迹来自服务端真实执行；运行中不要重复点击启动。
3. 展开工具事件看参数与返回，查看耗时与 Token。执行结束后先看业务验收，再看模型的交付文字。
4. 若超出演示时间，保留该运行并切到已有真实记录，明确说明切换。API 或执行失败时直接展示错误原因与已保存记录。

## 展示新增的“数据变化”页签

有前后快照的新运行可以直接展示数据修复的实际影响。推荐记录与可选的 Round 1 备份：

| 工单 | Run ID | 已记录的变化 |
|---|---|---|
| 最终验收退款记录，推荐 | `42fdb20f-0177-4f84-a529-f29b5b6803da` | 16 行 → 21 行；新增 5 条、内容变化 3 条；带真实语义复核 |
| R2b 退款备份 | `e9ed927d-921c-48ac-a521-e223afa31dde` | 同样记录 16 行 → 21 行、增加 5 条、变化 3 条和真实语义复核 |
| R1 退款备份 | `ec548a48-0875-45ec-a4aa-6a257e7dd467` | 16 行 → 21 行；新增 5 条、内容变化 3 条；可见规则由未通过变为通过 |
| R1 客户净收入模型备份 | `c91744f8-3379-4f9b-92ce-455ad2c7e585` | 空表 → 10 行；新增 10 条；可见规则由未通过变为通过 |

在「运行记录」打开退款记录，切到「数据变化」。先指明前后行数和字段变化，再展开「内容变化样本」：三条零申请金额退款的比例从 `NaN` 变为 `0`；展开「新增记录样本」查看补回的退款。下方分别保留修复前后的规则状态与数据样本。

讲解时说明：**变化只证明数据发生了什么，是否正确仍看“业务检查”中的独立验收。** 例如新增行数并不天然代表修复成功；字段变化与记录值变化分别记录，缺少稳定比对字段时不强算增删改。

旧记录没有历史快照时，页面显示「本次运行未记录数据变化」。这是实际缺失，不能根据最终表倒推出最初数据。

R1 真实只读验收记录位于 `artifacts/qa/round1_evidence_ui_20261025.json`。最终服务的桌面与 390px 验收为 `artifacts/qa/final_ui_20261025.json`：已核对推荐记录的通过状态、数据变化、语义复核，以及最终验收与公开 v3.1 两份报告的独立标题和正确通过数；无 JS／浏览器控制台错误、无非 GET 请求，未发起新模型运行。

## 解释语义复核与已知失败

初次 R2 合成回归为 5／6：复核器缺少完整 README 契约，建议给本来幂等的增量补丁添加 watermark；执行器随后从不含 `updated_at` 的目标表读取该列，导致构建失败。R2b 纳入 README、要求并校验公开需求引用，修订后 6／6，共 52 次模型调用、89 次工具调用、191,325 Tokens，估算 0.063835 USD。

历史公开 v3 没有实际触发复核，结果 0／2；公开 v3.1 两题各复核一次，仍为 0／2（组件 12／13、14／15），且复核后补丁都再次变化。该版退款窗口的 NULL 总体与客户过滤语义仍未正确。可以据此介绍历史失败如何推动修订，最新四题另看 RESULTS。完整证据与限制见 [FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md)。

离线审计已通过回归，当前完整测试结果见 ACCEPTANCE.md；可说明它检查协议覆盖、状态／构建、汇总与 Token、上游 pytest 证据和源快照绑定，不调用模型。它核验记录一致性，不把失败任务重新判为成功。

## 公开工程：导出并导入真实回放

v4.1 两轮已封存。首轮四题报告为 `results/v41_flash_round1_20261025.json`（3/4），第二轮商品为 `results/v41_flash_round2_20261025.json`（8/11、整题失败）。原始成功记录：退款 `b0f50ae7-e5f1-55c3-8cb7-4593afcdafeb`，库存 `f18fa4b5-d81c-5a74-9864-4d8502b9c5b3`；v4.1 第二轮商品 `4e97d643-006b-595f-9806-3e80fd8e1d64` 展示该版失败，不代表后续成品或辅助继续修复的结果。

`scripts/export_public_recordings.py` 读取已完成报告及其原始 agent JSON、JSONL、patch 和验收记录，写入 `examples/recorded_runs/`；`scripts/import_recordings.py` 将尚未导入的真实回放写入工作台 artifacts。两个脚本均不运行模型、数据库或验收，不产生模型 API 费用。

`scripts/export_reviewed_recordings.py results/acceptance/public_fixes_20261026.json` 单独转换已审阅成品验收：核对源文件、已应用 SQL、构建、原 pytest 和补丁哈希，设 `provider=operator_reviewed`、`mode=reviewed_patch`、模型指标为 0。它保留真实构建与验收证据，不生成模型事件或前后快照；验收报告仍在 `results/acceptance/`，不会进入 Agent 评测列表。

在当前机器只需导入已有录制并打开网页；导出命令需本机原始 artifacts/external 仍在：

```powershell
$publicReport = 'artifacts/evaluations/v41_flash_round1_20261025.json'
& '.venv/Scripts/python.exe' 'scripts/export_public_recordings.py' $publicReport
& '.venv/Scripts/python.exe' 'scripts/import_recordings.py'
```

导入后刷新工作台，在「运行记录」选择标有「公开项目」的真实记录，先看任务说明与模型，再看读取／查询、模型写入、dbt 执行和代码变更，最后展示独立原始验收。公开记录未保存前后快照时，数据变化页会说明缺失；用其实际轨迹与 patch 演示即可。

评分时先看 `grading_protocol`：产品题使用普通 pytest 的退出码及计数，其他组件协议看 component 与 reward；整题还要求有效执行、最终目标构建成功和 Agent 无执行错误。界面的已完成状态、组件部分通过和整题成功分别说明。

报告 JSON 的 `protocol` 保存任务、模型、预算与代码摘要，`records` 保留逐次执行，`summary` 是汇总。历史 54 次对照和 v4.1 两轮继续引用原报告；后续只进行已授权、已登记的 Flash 公开检查，回放与演示不触发额外实验。结束时提供仓库及选中记录的实际 Run ID 和报告，方便沿原始证据复核。

## 已验收的真实回放截图

前两张截图读取真实模型运行 `1dccea01-364d-4d87-9a77-ab6ed5449d85`（`revenue_fanout_dev / verified`）；后两张读取上表 R1 真实记录，仍可用于展示前后数据证据。截图保留各自版本来源，整体表现以评测报告为准。

- [执行轨迹与独立检查](screenshots/workbench.png)
- [实际模型补丁](screenshots/workbench-diff.png)
- [Round 1：真实前后数据与规则状态](screenshots/workbench-evidence.png)
- [Round 1：实际变化的记录样本](screenshots/workbench-evidence-details.png)

- [公开库存题真实通过回放](screenshots/public-flash.png)
- [第二轮商品8/11的真实失败回放](screenshots/public-flash-final.png)
- [已审阅商品成品：零模型调用、原 pytest 11/11](screenshots/public-reviewed.png)

成品回放的桌面与 390px 只读验收记录在 `artifacts/qa/public_reviewed_ui_20261026.json`：四条验收回放来源、模型零指标、原检查、真实 Diff 和缺失快照提示均已核对，0 浏览器错误、0 非 GET 请求；没有覆盖历史 Agent 失败记录。

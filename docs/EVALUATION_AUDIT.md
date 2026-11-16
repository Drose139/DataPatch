# 评测报告离线审计

审计已实现并通过测试。它读取已有 JSON 和源码快照，不调用模型、不重跑 dbt、不执行归档代码，也不修改原报告。入口是 `datapatch.audit.audit_report()` / `audit_reports()`；命令行使用 `scripts/audit_results.py`。

```powershell
.venv/Scripts/python.exe scripts/audit_results.py artifacts/evaluations --output artifacts/audits/final.json
```

输出顶层为 `audit`，包含 `passed`、`errors`、`warnings`、`checks`、逐报告结果和明确排除的报告。存在 error 时命令退出码为 1。warning 表示证据缺失或历史格式受限；不能把它解释为相应证据已经核验通过。

检查覆盖以下可从原始记录直接重算的项目：

- `planned_trials`、记录数、任务 × 模式 × 重复次数的完整组合，以及重复的 `run_id` / 组合。
- 通过任务必须执行完成且最终 build 成功；计数、耗时和估算费用非负，token 加和正确。
- 使用正式 `evaluation.summarize(records)` 重算汇总，逐模式检查通过率、调用数、token、费用和耗时等字段。
- 对公开 data-eng-bench 报告，核对 `raw_verifier` 的二元 reward、退出码、组件全部通过与最终 passed 一致；核对组件列表和原始 stdout，要求 pytest 的实际执行摘要，避免把“直接执行测试文件但未运行测试”计成通过。
- 对存在的源码 zip 核验归档 SHA-256、manifest 每个文件的 SHA-256、核心文件规范摘要与报告绑定。manifest 同时兼容 `files: {path: hash}` 和旧版 `files: [{path, sha256}]`。

公开报告使用 `planned_task_ids` 作为计划范围；本地合成报告使用 `task_ids`。单次协议缺少 `repeat` 时会明确 warning 并按 0 核验。无法获得 `raw_verifier`、原始 stdout、源码 zip 或源摘要时也会明确 warning，不生成相应的“证据已通过”声明。旧快照没有 manifest 时仍可根据归档中的 `src/datapatch/*.py` 与报告核验核心摘要，但无法核验逐文件 manifest 声明。

`*_unamended.json` 是保留的历史原记录，默认明确排除。它不能与修订后的正式报告重复计为额外实验。需要检查历史问题时显式执行：

```powershell
.venv/Scripts/python.exe scripts/audit_results.py artifacts/evaluations --include-unamended --output artifacts/audits/history.json
```

历史未修订报告中已知的“执行失败但旧 verification 仍为 passed”会使审计失败，这是预期结果。完整审计应在评测封存后运行；预审计可明确排除仍在写入的批次，但须在输出列出排除项，不能据此宣称整轮验收已完成。

审计通过只说明所检查的记录、汇总与归档证据一致。它不证明业务验收器覆盖充分，也不能消除公开开发题重复调试、样本少或运行环境差异造成的评测限制。

## 2026-10-25 最终离线验收

`artifacts/evaluations` 与用户可交付的 `results` 根目录各审计 10 份正式报告、1,463 项检查，均为 **0 errors、4 warnings**，命令均返回 0。两次审计前后的输入 JSON SHA-256 完全相同，未修改报告。

四项 warning 的含义相同：首轮公开报告缺少源码快照，因此不能补称该版源码已核验；`release_v2_smoke` 与 `synthetic_holdout` 两份旧归档没有 manifest，只核验了实际核心文件摘要与报告绑定，不能核验不存在的逐文件 manifest；保留的 `synthetic_holdout_20261025_unamended.json` 按明确历史策略排除，没有与修订版重复计数。后续有 manifest 的归档已实际逐文件核验。

正式审计输出为 `artifacts/audits/final_audit_20261025.json`，导出目录审计输出为 `artifacts/audits/exported_audit_20261025.json`。辅助审计和 UI 验证材料放在 `results/validation/`，不会被根目录的评测报告扫描混入实验统计。显式加入历史未修订报告的验收另已确认返回 1，并检出其旧的“执行失败仍为 passed”记录。

## 公开归档

发布时从源码 ZIP 中移除私人交接文档，并核对其余文件与实验归档的字节一致。ZIP 内的 `source-manifest.json` 记录公开版的逐文件摘要，`publication` 字段保存原 ZIP 与移除文件的 SHA-256。报告引用公开 ZIP 的摘要，核心源码摘要沿用实验记录。

验收日志和回放中的本机用户名已替换为 `local-user`。单题试跑的证据清单同时保存公开副本的哈希和修改前的哈希。[证据清单](../results/blind_20261026/manifest.json)

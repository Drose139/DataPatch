"""Export actual local results for source review and credential-free replay."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key not in {"api_key", "authorization"}}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, str):
        return value.replace(str(ROOT), "$PROJECT").replace(str(ROOT).replace("\\", "/"), "$PROJECT")
    return value


def main():
    reports = ROOT / "artifacts" / "evaluations"
    destination = ROOT / "results"
    destination.mkdir(exist_ok=True)
    recordings = ROOT / "examples" / "recorded_runs"
    recordings.mkdir(parents=True, exist_ok=True)
    sections = ["# 实际评测结果", "", "以下来自实际模型 API 调用和执行验收。原始失败保留；未运行的项目不填数字。", ""]
    acceptance_paths = [destination / "acceptance" / (name + ".json") for name in
                        ("public_core_recheck_20261026", "public_expanded_fixes_20261026", "public_cohort_infra_retry_20261026")]
    if all(path.is_file() for path in acceptance_paths):
        acceptances = [json.loads(path.read_text(encoding="utf-8")) for path in acceptance_paths]
        if all(report.get("status") == "completed" for report in acceptances):
            rows = [row for report in acceptances for row in report["records"]]
            accepted = sum(row["verification"]["passed"] is True for row in rows)
            final_tasks = {row["task_id"]: row for row in rows}
            final_accepted = sum(row["verification"]["passed"] is True for row in final_tasks.values())
            sections += ["## 经审阅公开成品验收（零模型API）", "",
                         f"{final_accepted}/{len(final_tasks)} 个不同任务最终通过；{accepted}/{len(rows)} 次实际尝试通过，包含一次依赖准备失败及事先登记的单题补验。与自主 Agent 成绩分开。",
                         "原四题要求 dbt build；新增四题按上游物化与原 pytest 协议、显式 UTC。时区题附加主键质量失败仍保留，不计为全部 dbt tests 通过。", "",
                         "[逐题与环境边界](PUBLIC_EIGHT_TASKS.md)", ""]
    chosen = []
    for name in ["synthetic_holdout_20261025", "release_v2_smoke_20261025", "round1_evidence_20261025", "round2_semantic_review_20261025", "round2b_contract_review_20261025", "final_acceptance_20261025", "public_native_subset_20261025", "public_native_v2_20261025", "public_native_v3_20261025", "public_native_v31_20261025", "public_native_v4_20261025", "v41_flash_round1_20261025", "v41_flash_round2_20261025", "v42_relationship_product_20261026", "v43_contract_repair_20261026"]:
        path = reports / f"{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") not in {"completed", "budget_stopped"}:
            raise RuntimeError(f"Refusing to publish unfinished report: {name}")
        sanitized = clean(data)
        (destination / path.name).write_text(json.dumps(sanitized, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        markdown = path.with_suffix(".md")
        if markdown.exists():
            (destination / markdown.name).write_text(clean(markdown.read_text(encoding="utf-8")), encoding="utf-8")
        unamended = path.with_name(path.stem + "_unamended.json")
        if unamended.exists():
            (destination / unamended.name).write_text(json.dumps(clean(json.loads(unamended.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2), encoding="utf-8")
        sections += [f"## {data.get('title', name)}", "", f"实验编号：`{name}`", "", str(data.get("provenance", "")), "", f"完整记录：[JSON](../results/{name}.json) · [报告](../results/{name}.md)", "", "| 模式 | 任务通过/实际运行 | 成功率 | 平均耗时 | Tokens | 估算USD |", "|---|---:|---:|---:|---:|---:|"]
        for row in data.get("summary", []):
            sections.append(f"| {row.get('mode')} | {row.get('passed', 0)}/{row.get('trials', 0)} | {row.get('task_success_rate', 0):.1%} | {row.get('mean_elapsed_seconds', '—')} | {row.get('total_tokens', '—')} | {row.get('estimated_cost_usd', '—')} |")
        sections += ["", "费用按配置单价估算，未扣缓存折扣，实际账单以服务商为准。", ""]
        if data.get("dataset", "").startswith("datapatch-synthetic"):
            sections += ["保留集仅改变固定种子源数据，任务语义与开发集相同。样本较小；结果不能证明跨项目泛化或统计显著优势。构建成功与最终数据正确分别记录。", ""]
            successes = [r for r in data.get("records", []) if (r.get("verification") or {}).get("passed") and r.get("mode") == "verified"]
            failures = [r for r in data.get("records", []) if not (r.get("verification") or {}).get("passed")]
            chosen.extend(successes[:2])
            chosen.extend(failures[:1])
            if data.get("grading_amendment"):
                sections += [f"评分修订：要求执行完成、最终构建成功及独立输出验收通过，改变 {data['grading_amendment']['changed_trial_grades']} 次运行判定；没有重跑模型。修订前报告另存。", ""]
        else:
            sections += ["这是固定公开任务的 Native 开发子集。上游版本和路径适配有记录，未按官方 Harbor 全量/多次协议运行；不与官方排行榜直接比较。组件部分通过不等于整题通过。", ""]
            if data.get("protocol", {}).get("assistance"):
                sections += ["此记录使用项目方公开业务契约辅助；v43 从已有失败候选继续修复，不属于未经辅助的新题盲测。契约来源与初始候选哈希保存在报告。", ""]
    # Keep an independently recorded successful development run for the demo guide.
    dev_path = ROOT / "artifacts/runs/1dccea01-364d-4d87-9a77-ab6ed5449d85/run.json"
    if dev_path.exists():
        chosen.insert(0, json.loads(dev_path.read_text(encoding="utf-8")))
    for record in chosen:
        output = recordings / f"{record['run_id']}.json"
        record = clean(record)
        record["recording_source"] = "actual DeepSeek API run; archived recording, not a new live execution"
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    source = reports / "synthetic_holdout_20261025_source.zip"
    if source.exists():
        shutil.copy2(source, destination / "evaluated_source.zip")
    for source in reports.glob("*_source.zip"):
        shutil.copy2(source, destination / source.name)
    validation = destination / "validation"
    validation.mkdir(exist_ok=True)
    for directory, namespace in (("audits", ""), ("qa", ""), ("costs", "costs"), ("protocols", "protocols")):
        target = validation / namespace
        target.mkdir(exist_ok=True)
        for source in (ROOT / "artifacts" / directory).glob("*.json"):
            (target / source.name).write_text(json.dumps(clean(json.loads(source.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2), encoding="utf-8")
    sections += ["## 版本和复现", "", "评测协议中的 source_sha256 对应启动时源代码；[首轮评测源代码快照](../results/evaluated_source.zip)及后续各版源码归档随结果保存。运行依赖锁定在 requirements.lock。", "", "网页演示可使用这些真实录制记录：", "", "```powershell", ".\\.venv\\Scripts\\python.exe scripts/import_recordings.py", "```", "", "该命令只导入已记录的实际运行，不调用模型、不重新计算成绩。离线审计命令见 [EVALUATION_AUDIT.md](EVALUATION_AUDIT.md)；审计检查报告一致性，不改变原有业务成绩。"]
    (ROOT / "docs/RESULTS.md").write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"Exported results and {len(chosen)} actual recordings")


if __name__ == "__main__":
    main()


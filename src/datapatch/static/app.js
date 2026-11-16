"use strict";

const $ = (id) => document.getElementById(id);
const state = { tasks: [], runs: [], selectedTask: null, run: null, replay: false, config: {}, timer: null, loading: false, view: "workbench", report: null };
const modes = { baseline: "Baseline · 单次补丁", react: "ReAct · 通用工具调用", context: "Context · 结构化上下文", verified: "Verified · 校验与恢复" };
const activeStatuses = new Set(["queued", "running", "pending", "created"]);
const json = (data) => JSON.stringify(data, null, 2);

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined && value !== null) node.textContent = String(value);
  return node;
}

function showError(error) {
  $("error-message").textContent = error instanceof Error ? error.message : String(error);
  $("error-banner").classList.remove("hidden");
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.remove("hidden");
  window.setTimeout(() => $("toast").classList.add("hidden"), 3500);
}

async function api(path, options) {
  const response = await fetch(`/api${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : json(payload.detail || payload);
    throw new Error(detail || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

function asList(payload, keys = []) {
  if (Array.isArray(payload)) return payload;
  for (const key of keys) if (Array.isArray(payload?.[key])) return payload[key];
  return [];
}

function empty(container, title, description, icon) {
  container.replaceChildren();
  const box = element("div", "empty-state");
  if (icon) box.append(element("span", "empty-icon", icon));
  box.append(element("h3", "", title));
  if (description) box.append(element("p", "", description));
  container.append(box);
}

function rawDetails(data, label = "查看原始数据", className = "event-details") {
  const details = element("details", className);
  details.append(element("summary", "", label), element("pre", "", json(data)));
  return details;
}

function taskId(task) { return task.id || task.task_id; }
function taskName(task) { return task.title || task.name || taskId(task); }
function dateText(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function updateStartButton() {
  const active = state.run && activeStatuses.has(state.run.status);
  const configured = state.config.api_key_configured === true;
  $("start-run").disabled = !state.selectedTask || !configured || state.loading || active;
  $("start-run").firstElementChild.textContent = state.loading ? "正在启动…" : active ? "正在执行…" : "启动修复";
  $("execution-note").textContent = !configured ? "请在服务端配置模型 API 密钥" : active ? "执行中 · 记录每一步真实反馈" : "使用真实模型 API 执行";
}

async function loadConfig() {
  state.config = await api("/config");
  $("model-label").textContent = (state.config.model || "DeepSeek") + (state.config.thinking_enabled ? " · 思考" : "");
  $("connection-dot").className = `connection-dot ${state.config.api_key_configured ? "" : "bad"}`;
  const label = $("connection-label");
  label.replaceChildren(document.createTextNode(state.config.api_key_configured ? "模型 API 已配置" : "模型 API 待配置"), element("small", "", "模型密钥仅保存在服务端"));
  updateStartButton();
}

function renderTasks() {
  const list = $("task-list");
  list.replaceChildren();
  const picker = $("task-picker");
  picker.replaceChildren();
  $("task-count").textContent = String(state.tasks.length).padStart(2, "0");
  for (const task of state.tasks) {
    const button = element("button", `task-item ${taskId(state.selectedTask || {}) === taskId(task) ? "active" : ""}`);
    const label = element("div");
    label.append(element("strong", "", taskName(task)), element("small", "", taskId(task)));
    button.append(label);
    button.addEventListener("click", () => selectTask(task).catch(showError));
    list.append(button);
    const option = element("option", "", taskName(task));
    option.value = taskId(task);
    option.selected = taskId(state.selectedTask || {}) === taskId(task);
    picker.append(option);
  }
  if (!state.tasks.length) list.append(element("p", "sidebar-hint", "任务库暂无任务。"));
}

async function selectTask(task) {
  const mode = $("mode-select");
  if (mode.selectedOptions[0]?.dataset.recordedOnly) {
    mode.querySelectorAll("option[data-recorded-only]").forEach((option) => option.remove());
    mode.value = "verified";
  }
  const detail = await api(`/tasks/${encodeURIComponent(taskId(task))}`);
  state.selectedTask = { ...task, ...detail };
  $("task-id-label").textContent = taskId(state.selectedTask);
  $("task-title").textContent = taskName(state.selectedTask);
  const description = state.selectedTask.description || state.selectedTask.prompt || state.selectedTask.instruction || state.selectedTask.issue || "审阅任务上下文，启动 Agent 处理本次数据工程工单。";
  $("task-description").textContent = typeof description === "string" ? description : json(description);
  $("task-json").textContent = json(detail);
  renderTasks();
  updateStartButton();
  switchView("workbench");
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((section) => section.classList.add("hidden"));
  $(`${view}-view`).classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $("view-label").textContent = { workbench: "修复工作台", history: "运行记录", evaluation: "对比评测" }[view];
  if (view === "history") loadRuns().catch(showError);
  if (view === "evaluation") loadReports().catch(showError);
}

function getChecks(run) {
  const checks = run.verification?.checks || run.checks || [];
  if (Array.isArray(checks)) return checks;
  if (typeof checks === "object" && checks !== null) return Object.entries(checks).map(([name, value]) => typeof value === "object" && value !== null ? { name, ...value } : { name, passed: value });
  return [];
}

function statusInfo(run) {
  if (["failed", "error"].includes(run.status)) return ["执行失败", "failed"];
  if (activeStatuses.has(run.status)) return [run.status === "queued" ? "排队中" : "执行中", "running"];
  if (run.verification?.passed === true) return ["验证通过", "success"];
  if (run.verification?.passed === false) return ["验证未通过", "failed"];
  return [{ completed: "运行完成", cancelled: "已取消", stopped: "已停止" }[run.status] || run.status || "等待运行", "idle"];
}

function renderMetrics(run) {
  const metrics = run.metrics || run.usage || {};
  let elapsed = metrics.elapsed_seconds ?? metrics.duration_seconds ?? run.elapsed_seconds;
  if (elapsed === undefined && run.started_at) elapsed = ((run.finished_at ? new Date(run.finished_at) : new Date()) - new Date(run.started_at)) / 1000;
  $("metric-duration").replaceChildren(document.createTextNode(Number.isFinite(Number(elapsed)) ? Math.max(0, Number(elapsed)).toFixed(1) : "—"), element("small", "", "s"));
  const events = run.events || [];
  const calls = metrics.model_calls ?? run.model_calls ?? events.filter((event) => event.type === "model").length;
  $("metric-calls").replaceChildren(document.createTextNode(String(calls)), element("small", "", "次"));
  const tokens = metrics.total_tokens ?? ((metrics.prompt_tokens || 0) + (metrics.completion_tokens || 0));
  $("metric-tokens").textContent = tokens.toLocaleString("zh-CN");
  $("metric-tokens").title = `输入 ${metrics.prompt_tokens || 0} / 输出 ${metrics.completion_tokens || 0}${metrics.estimated_cost_usd != null ? ` · 预估 $${Number(metrics.estimated_cost_usd).toFixed(4)}` : ""}`;
  const checks = getChecks(run);
  $("metric-checks").textContent = checks.length ? `${checks.filter((check) => check.passed === true).length} / ${checks.length}` : "—";
}

const eventTitles = { status: "状态更新", model: "模型响应", tool: "工具调用", validation: "验证结果", error: "执行错误", final: "完成反馈" };
function renderTimeline(run) {
  const events = asList(run.events || [], ["events"]);
  $("event-count").textContent = events.length;
  if (!events.length) { empty($("timeline"), activeStatuses.has(run.status) ? "Agent 已启动，等待首条反馈" : "本次运行没有执行事件", "运行事件会自动更新，无需重复启动。", "⌁"); return; }
  const timeline = $("timeline");
  const expanded = new Set(Array.from(timeline.querySelectorAll("details[open]")).map((node) => node.dataset.seq));
  const nearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 80;
  timeline.replaceChildren();
  for (let index = 0; index < events.length; index++) {
    const event = events[index];
    const item = element("article", "timeline-event");
    const heading = element("div", "event-heading");
    const title = element("span", "", event.name || event.tool || eventTitles[event.type] || event.type || `步骤 ${index + 1}`);
    const time = element("span", "event-time", event.timestamp ? new Date(event.timestamp).toLocaleTimeString("zh-CN", { hour12: false }) : `#${event.seq ?? index + 1}`);
    heading.append(title, time);
    item.append(heading);
    const content = event.content ?? event.message ?? event.summary;
    if (content) item.append(element("div", "event-summary", typeof content === "string" ? content.slice(0, 900) : json(content).slice(0, 900)));
    const stats = event.usage;
    const eventElapsed = event.elapsed_seconds ?? event.latency_seconds;
    if (stats || eventElapsed != null) {
      const usageLabel = stats ? `${stats.total_tokens || ((stats.prompt_tokens || 0) + (stats.completion_tokens || 0))} tokens` : "";
      const timeLabel = eventElapsed != null ? `${Number(eventElapsed).toFixed(2)} s` : "";
      item.append(element("div", "event-kind", [usageLabel, timeLabel].filter(Boolean).join(" · ")));
    }
    const details = rawDetails(event, event.type === "tool" ? "查看工具参数与返回" : "查看完整事件");
    details.dataset.seq = String(event.seq ?? index);
    details.open = expanded.has(details.dataset.seq);
    item.append(details);
    timeline.append(item);
  }
  if (nearBottom && activeStatuses.has(run.status)) timeline.scrollTop = timeline.scrollHeight;
}

function renderChecks(run) {
  const checks = getChecks(run);
  $("checks-count").textContent = checks.length;
  if (!checks.length) { empty($("checks-result"), "暂未生成业务检查结果", activeStatuses.has(run.status) ? "Agent 正在执行；验证结果将自动显示。" : run.verification?.summary || "查看执行轨迹与运行数据了解本次结果。", "✓"); return; }
  const box = $("checks-result");
  box.replaceChildren();
  if (run.verification?.summary) box.append(element("p", "report-description", run.verification.summary));
  if (run.project_quality?.build?.success === false) {
    box.append(element("p", "evidence-notice", "附加 dbt build 检查未通过。此记录按上游题目协议，以实际模型物化和原始 pytest 验收；附加质量检查的失败仍保留在下方详情中。"));
    box.append(rawDetails(run.project_quality, "查看附加质量检查原始失败"));
  }
  for (const check of checks) {
    const row = element("div", "check-row");
    const passed = check.passed === true;
    const failed = check.passed === false;
    row.append(element("span", `check-symbol ${failed ? "failed" : passed ? "" : "unknown"}`, passed ? "✓" : failed ? "×" : "·"));
    const body = element("div", "check-body");
    body.append(element("h4", "", check.name || check.id || "业务检查"));
    if (check.description || check.message) body.append(element("p", "", check.description || check.message));
    if (check.expected !== undefined || check.actual !== undefined) body.append(element("p", "", `期望：${typeof check.expected === "object" ? json(check.expected) : check.expected ?? "—"}　实际：${typeof check.actual === "object" ? json(check.actual) : check.actual ?? "—"}`));
    body.append(rawDetails(check, "检查详情"));
    row.append(body, element("span", `status-badge ${passed ? "success" : failed ? "failed" : "idle"}`, passed ? "通过" : failed ? "未通过" : "待定"));
    box.append(row);
  }
}

function renderDiff(run) {
  let diff = run.diff || run.patch || "";
  if (typeof diff !== "string") diff = json(diff);
  if (!diff.trim()) { empty($("diff-result"), "暂无代码变更", "本次运行尚未生成补丁，或未修改任何文件。"); return; }
  const pre = element("pre", "diff-code");
  for (const line of diff.split("\n")) {
    const kind = line.startsWith("@@") || line.startsWith("diff ") || line.startsWith("+++") || line.startsWith("---") ? "header" : line.startsWith("+") ? "add" : line.startsWith("-") ? "remove" : "";
    pre.append(element("span", `diff-line ${kind}`, line || " "));
  }
  $("diff-result").replaceChildren(pre);
}

function evidenceNumber(value, signed = false) {
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  return `${signed && number > 0 ? "+" : ""}${number.toLocaleString("zh-CN")}`;
}

function evidenceValue(value) {
  if (value === undefined) return "—";
  if (value === null) return "NULL";
  return typeof value === "object" ? json(value) : String(value);
}

function evidenceTable(rows, columns, changedColumns = []) {
  const wrapper = element("div", "evidence-table-scroll");
  const table = element("table", "evidence-table");
  const fields = columns || [...new Set(rows.flatMap((row) => Object.keys(row || {})))];
  const header = element("tr");
  fields.forEach((name) => header.append(element("th", "", name)));
  const head = element("thead");
  head.append(header);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    for (const name of fields) {
      const value = evidenceValue(row?.[name]);
      const cell = element("td", changedColumns.includes(name) ? "value-changed" : "", value.length > 150 ? `${value.slice(0, 147)}…` : value);
      cell.title = value;
      tr.append(cell);
    }
    body.append(tr);
  }
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}

function evidenceSection(title, subtitle) {
  const section = element("section", "evidence-section");
  const heading = element("div", "evidence-section-heading");
  heading.append(element("h4", "", title));
  if (subtitle) heading.append(element("span", "", subtitle));
  section.append(heading);
  return section;
}

function evidenceMatchReason(before, after) {
  if (!before?.available || !after?.available) return "修复前后数据尚未齐备，暂不能逐条比较。";
  if (before.truncated || after.truncated) return "数据超出本次逐条比较范围，仅展示样本与可确认的统计。";
  const statuses = [before.key_validation?.status, after.key_validation?.status];
  if (statuses.includes("missing_columns")) return "比对字段在数据中缺失，无法可靠匹配记录。";
  if (statuses.includes("null_keys")) return "比对字段存在空值，无法可靠匹配记录。";
  if (statuses.includes("duplicate_keys")) return "比对字段存在重复，无法可靠匹配记录。";
  if (!before.key_columns?.length || !after.key_columns?.length) return "未指定稳定的比对字段，仅展示行数、字段与数据样本。";
  return "当前数据无法可靠地逐条匹配，仅展示可确认的统计与样本。";
}

function renderSchemaEvidence(comparison) {
  const schema = comparison?.schema;
  const section = evidenceSection("字段变化");
  if (!schema || schema.comparable === false) {
    section.append(element("p", "evidence-note", "修复前后字段信息未齐备，暂不能确认字段变化。"));
    return section;
  }
  const changes = [
    ...(schema.added || []).map((field) => ({ name: field.name, detail: field.type, label: "新增", kind: "added" })),
    ...(schema.removed || []).map((field) => ({ name: field.name, detail: field.type, label: "移除", kind: "removed" })),
    ...(schema.type_changed || []).map((field) => ({ name: field.name, detail: `${field.before} → ${field.after}`, label: "类型变化", kind: "changed" })),
  ];
  if (!changes.length) section.append(element("p", "evidence-note", "未发现字段新增、移除或类型变化。"));
  else for (const change of changes) {
    const row = element("div", "schema-change-row");
    row.append(element("span", `evidence-change-label ${change.kind}`, change.label), element("strong", "", change.name), element("span", "evidence-field-type", change.detail));
    section.append(row);
  }
  return section;
}

function renderChangedSamples(samples) {
  const wrapper = element("div", "changed-record-list");
  for (const sample of samples) {
    const record = element("div", "changed-record");
    const keyLabel = Object.entries(sample.key || {}).map(([name, value]) => `${name}: ${evidenceValue(value)}`).join(" · ");
    record.append(element("p", "changed-record-key", keyLabel || "记录对比"));
    const columns = sample.changed_columns?.length ? sample.changed_columns : [...new Set([...Object.keys(sample.before || {}), ...Object.keys(sample.after || {})])];
    const rows = [{ "阶段": "修复前", ...sample.before }, { "阶段": "修复后", ...sample.after }];
    record.append(evidenceTable(rows, ["阶段", ...columns], sample.changed_columns || []));
    wrapper.append(record);
  }
  return wrapper;
}

function renderContractEvidence(evidence) {
  const before = evidence.contracts_before;
  const after = evidence.contracts_after;
  const section = evidenceSection("业务规则检查", "修复前 → 修复后");
  const beforeChecks = Array.isArray(before?.checks) ? before.checks : [];
  const afterChecks = Array.isArray(after?.checks) ? after.checks : [];
  const summaries = element("div", "contract-status-grid");
  for (const [label, result, checks] of [["修复前", before, beforeChecks], ["修复后", after, afterChecks]]) {
    const item = element("div", "contract-status-item");
    let status = "未记录";
    let kind = "idle";
    if (result?.error) { status = "检查未完成"; kind = "failed"; }
    else if (result?.available === false || (result && checks.length === 0)) status = "未提供检查";
    else if (result?.passed === true) { status = "通过"; kind = "success"; }
    else if (result?.passed === false) { status = "未通过"; kind = "failed"; }
    item.append(element("span", "", label), element("span", `status-badge ${kind}`, status));
    summaries.append(item);
  }
  section.append(summaries);
  const names = [...new Set([...beforeChecks, ...afterChecks].map((check) => check.name || check.id))];
  if (!names.length) {
    section.append(element("p", "evidence-note", before?.available === false || after?.available === false ? "本任务未提供额外的可见业务规则，独立最终验收见“业务检查”。" : "尚未记录修复前后的规则检查结果。"));
    return section;
  }
  const table = element("table", "evidence-table contract-comparison");
  const head = element("thead");
  const heading = element("tr");
  ["检查项", "修复前", "修复后"].forEach((name) => heading.append(element("th", "", name)));
  head.append(heading);
  const body = element("tbody");
  for (const name of names) {
    const row = element("tr");
    row.append(element("td", "contract-name", name));
    for (const checks of [beforeChecks, afterChecks]) {
      const check = checks.find((entry) => (entry.name || entry.id) === name);
      const cell = element("td");
      cell.append(element("span", `status-badge ${check?.passed === true ? "success" : check?.passed === false ? "failed" : "idle"}`, check?.passed === true ? "通过" : check?.passed === false ? "未通过" : "未记录"));
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  const scroll = element("div", "evidence-table-scroll");
  scroll.append(table);
  section.append(scroll);
  return section;
}

function renderSnapshotSamples(snapshot, label, buildSuccess) {
  const details = element("details", "evidence-sample-details");
  details.append(element("summary", "", `${label}数据样本${snapshot?.available ? ` · ${evidenceNumber(snapshot.row_count)} 行` : ""}`));
  if (!snapshot?.available) details.append(element("p", "evidence-note", "没有可用的数据快照。"));
  else {
    if (buildSuccess === false) details.append(element("p", "evidence-notice", "构建未通过，样本来自现有数据，可能未应用最新代码。"));
    const rows = Array.isArray(snapshot.sample_rows) ? snapshot.sample_rows : [];
    if (rows.length) details.append(evidenceTable(rows));
    else details.append(element("p", "evidence-note", snapshot.row_count === 0 ? "当前表没有记录。" : "未保存数据样本。"));
  }
  return details;
}

function renderDataEvidence(run) {
  const evidence = run.data_evidence;
  const box = $("data-result");
  const openDetails = new Set(Array.from(box.querySelectorAll("details[open]")).map((node) => node.dataset.evidenceId));
  if (!evidence) {
    empty(box, activeStatuses.has(run.status) ? "数据快照尚未生成" : "本次运行未记录数据变化", activeStatuses.has(run.status) ? "完成修复后将显示前后数据与记录差异。" : "这条运行没有保存前后快照，无法还原数据变化。", "⇄");
    return;
  }
  box.replaceChildren();
  const body = element("div", "data-evidence");
  const before = evidence.before;
  const after = evidence.after;
  const comparison = evidence.comparison;
  const header = element("div", "evidence-intro");
  const heading = element("div", "evidence-section-heading");
  heading.append(element("h4", "", before?.table || after?.table || "输出数据"), element("span", "evidence-stage", comparison?.status === "complete" ? "比较已完成" : comparison?.status === "partial" ? "部分数据可比较" : activeStatuses.has(run.status) ? "等待数据" : "数据不可比较"));
  header.append(heading, element("p", "evidence-note", "这里展示数据发生了什么变化；修复是否正确，请查看独立业务检查。"));
  body.append(header);
  if (evidence.initial_build_success === false || evidence.final_build_success === false) body.append(element("p", "evidence-notice", evidence.final_build_success === false ? "修复后的构建未通过；现有表可能保留旧结果，不能据此判断修复已生效。" : "修复前的构建未通过；初始快照可能不代表当时的模型输出。"));
  const counts = comparison?.counts || {};
  const statGrid = element("div", "evidence-count-grid");
  for (const [label, value, signed] of [["修复前行数", counts.before ?? before?.row_count, false], ["修复后行数", counts.after ?? after?.row_count, false], ["行数变化", counts.delta, true]]) {
    const card = element("div", "evidence-count");
    card.append(element("span", "", label), element("strong", "", evidenceNumber(value, signed)));
    statGrid.append(card);
  }
  body.append(statGrid, renderSchemaEvidence(comparison));
  const keyed = comparison?.keyed_diff;
  const records = evidenceSection("记录变化", keyed?.supported && keyed.keys?.length ? `按 ${keyed.keys.join("、")} 对比` : "");
  const changes = element("div", "evidence-change-grid");
  for (const [kind, label, count] of [["added", "新增", keyed?.added_count], ["removed", "移除", keyed?.removed_count], ["changed", "内容变化", keyed?.changed_count]]) {
    const card = element("div", `evidence-change-card ${kind}`);
    card.append(element("span", "", label), element("strong", "", keyed?.supported ? evidenceNumber(count) : "—"));
    changes.append(card);
  }
  records.append(changes);
  if (!keyed?.supported) records.append(element("p", "evidence-note", evidenceMatchReason(before, after)));
  else {
    const schema = comparison.schema || {};
    if ((schema.added || []).length + (schema.removed || []).length + (schema.type_changed || []).length) records.append(element("p", "evidence-note", "记录内容按前后共有且类型一致的字段比较；字段变化已在上方单列。"));
    if (keyed.unchanged_count != null) records.append(element("p", "evidence-note", `${evidenceNumber(keyed.unchanged_count)} 条记录在已比较字段中保持不变。`));
    for (const [kind, label] of [["changed", "内容变化样本"], ["added", "新增记录样本"], ["removed", "移除记录样本"]]) {
      const samples = keyed.samples?.[kind];
      if (!Array.isArray(samples) || !samples.length) continue;
      const details = element("details", "evidence-sample-details");
      details.dataset.evidenceId = kind;
      details.open = openDetails.has(kind);
      details.append(element("summary", "", `${label} · ${samples.length} 条`));
      details.append(kind === "changed" ? renderChangedSamples(samples) : evidenceTable(samples));
      records.append(details);
    }
  }
  body.append(records, renderContractEvidence(evidence));
  const snapshots = evidenceSection("前后数据样本", "仅展示已保存的样本");
  for (const [snapshot, label, buildSuccess, key] of [[before, "修复前", evidence.initial_build_success, "before"], [after, "修复后", evidence.final_build_success, "after"]]) {
    const details = renderSnapshotSamples(snapshot, label, buildSuccess);
    details.dataset.evidenceId = key;
    details.open = openDetails.has(key);
    snapshots.append(details);
  }
  body.append(snapshots);
  box.append(body);
}

function renderRun(run) {
  state.run = run;
  const [label, kind] = statusInfo(run);
  $("run-status").textContent = label;
  $("run-status").className = `status-badge ${kind} ${kind === "running" ? "pulse" : ""}`;
  $("run-id-label").textContent = run.run_id || run.id || "—";
  $("run-id-label").title = run.run_id || run.id || "";
  const actualModel = ["deepseek", "openai"].includes(run.provider);
  $("replay-tag").classList.toggle("hidden", !state.replay);
  $("replay-tag").textContent = run.provider === "operator_reviewed"
    ? "已审阅补丁验收回放 · 未调用模型"
    : run.public_contracts ? "真实模型运行回放 · 项目契约辅助"
    : actualModel ? "已记录真实运行回放" : "已记录运行回放 · 离线验证";
  $("timeline-label").textContent = state.replay ? "已保存的原始事件" : activeStatuses.has(run.status) ? "每秒更新" : "工具调用与反馈";
  $("run-json").textContent = json(run);
  renderMetrics(run);
  renderTimeline(run);
  renderChecks(run);
  renderDiff(run);
  renderDataEvidence(run);
  updateStartButton();
}

function stopPolling() {
  if (state.timer !== null) window.clearTimeout(state.timer);
  state.timer = null;
}

async function refreshRun(runId) {
  stopPolling();
  try {
    const run = await api(`/runs/${encodeURIComponent(runId)}`);
    if (state.run && (state.run.run_id || state.run.id) !== runId) return;
    renderRun(run);
    if (activeStatuses.has(run.status)) state.timer = window.setTimeout(() => refreshRun(runId), 1000);
    else loadRuns().catch(showError);
  } catch (error) {
    showError(new Error(`读取运行记录失败：${error.message}。可在运行记录页重新打开。`));
  }
}

async function openRun(runId, replay = true) {
  stopPolling();
  state.run = null;
  state.replay = replay;
  const run = await api(`/runs/${encodeURIComponent(runId)}`);
  renderRun(run);
  if (run.task_id) {
    const task = state.tasks.find((entry) => taskId(entry) === run.task_id);
    if (task) await selectTask(task);
    else {
      // Public project recordings are genuine runs outside the fixture catalog.
      // Show their own ticket rather than retaining the previous fixture title.
      state.selectedTask = null;
      $("task-id-label").textContent = run.task_id;
      $("task-title").textContent = run.task?.title || run.task_id;
      $("task-description").textContent = run.task?.description || "公开项目实际运行记录；可查看原始执行轨迹与验收。";
      $("task-json").textContent = json(run.task || { task_id: run.task_id });
      renderTasks();
      updateStartButton();
    }
  }
  const modeSelect = $("mode-select");
  modeSelect.querySelectorAll("option[data-recorded-only]").forEach((option) => option.remove());
  if (run.mode && !Array.from(modeSelect.options).some((option) => option.value === run.mode)) {
    const option = element("option", "", run.mode === "reviewed_patch" ? "已审阅成品 · 原始测试验收" : run.mode);
    option.value = run.mode;
    option.disabled = true;
    option.dataset.recordedOnly = "true";
    modeSelect.append(option);
  }
  if (run.mode) modeSelect.value = run.mode;
  switchView("workbench");
  if (activeStatuses.has(run.status)) state.timer = window.setTimeout(() => refreshRun(runId), 1000);
}

async function startRun() {
  if (!state.selectedTask || state.loading) return;
  const maxSteps = Number($("max-steps").value);
  if (!Number.isInteger(maxSteps) || maxSteps < 1 || maxSteps > 40) { showError("最大步数需要是 1 到 40 之间的整数。"); return; }
  state.loading = true;
  updateStartButton();
  $("error-banner").classList.add("hidden");
  try {
    const started = await api("/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: taskId(state.selectedTask), mode: $("mode-select").value, provider: "deepseek", max_steps: maxSteps }) });
    await openRun(started.run_id || started.id, false);
    toast("运行已启动，真实执行事件将自动更新。");
  } catch (error) { showError(error); }
  finally { state.loading = false; updateStartButton(); }
}

async function loadRuns() {
  state.runs = asList(await api("/runs"), ["runs", "items"]);
  $("history-count").textContent = state.runs.length;
  if (!state.runs.length) { empty($("history-list"), "还没有运行记录", "启动一次修复后，即可在这里打开完整执行记录。", "◷"); return; }
  const box = $("history-list");
  box.replaceChildren();
  for (const run of state.runs) {
    const [label, kind] = statusInfo(run);
    const row = element("button", "history-row");
    const title = element("div");
    const task = state.tasks.find((entry) => taskId(entry) === run.task_id);
    title.append(element("strong", "", run.task?.title || (task ? taskName(task) : run.task_id)), element("small", "", run.run_id || run.id));
    row.append(title, element("span", "", modes[run.mode] || run.mode), element("span", `status-badge ${kind}`, label), element("time", "", dateText(run.started_at || run.created_at)), element("span", "", "↗"));
    row.addEventListener("click", () => openRun(run.run_id || run.id, true).catch(showError));
    box.append(row);
  }
}

function reportRows(report) {
  for (const field of ["summary", "comparisons", "aggregates", "aggregate", "by_mode", "modes", "results"]) {
    const value = report[field];
    if (Array.isArray(value) && value.length && typeof value[0] === "object") return value;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const entries = Object.entries(value);
      if (entries.length && entries.every(([, record]) => record && typeof record === "object" && !Array.isArray(record))) return entries.map(([mode, record]) => ({ mode, ...record }));
    }
  }
  return [];
}

const columnLabels = { mode: "执行方案", provider: "模型来源", model: "模型", total: "任务数", tasks: "任务数", count: "次数", task_count: "任务数", passed: "通过数", trials: "实际运行", task_success_rate: "任务通过率", all_repeats_success_rate: "多次全成功率", min_repeats_per_task: "每题最少重复", final_build_success_rate: "构建通过率", infrastructure_failures: "执行失败", tool_calls: "工具调用", pass_rate: "通过率", success_rate: "成功率", success: "成功数", average_tokens: "平均 Token", avg_tokens: "平均 Token", total_tokens: "Token 总量", avg_elapsed_seconds: "平均耗时 / s", elapsed_seconds: "耗时 / s", model_calls: "模型调用", total_runs: "运行数", verified_pass_rate: "验证通过率", mean_tokens: "平均 Token", mean_elapsed_seconds: "平均耗时 / s", estimated_cost_usd: "预估成本 / USD" };

async function openReport(report) {
  const name = typeof report === "string" ? report : report.name || report.filename || report.id;
  const data = await api(`/reports/${encodeURIComponent(name)}`);
  state.report = name;
  $("report-title").textContent = report.title || name;
  document.querySelectorAll(".report-item").forEach((button) => button.classList.toggle("active", button.dataset.name === name));
  const box = $("report-body");
  box.replaceChildren();
  if (data.status) {
    const statusLabel = { running: "评测进行中", completed: "评测已完成", budget_stopped: "预算停止" }[data.status] || data.status;
    const progress = Array.isArray(data.records) ? ` · 已记录 ${data.records.length}${data.planned_trials != null ? ` / ${data.planned_trials}` : ""} 次运行` : "";
    box.append(element("p", "report-description", `${statusLabel}${progress}${data.protocol?.model ? ` · ${data.protocol.model}` : ""}`));
  }
  if (data.provenance) box.append(element("p", "report-description", data.provenance));
  box.append(element("p", "report-description", data.description || "以下为本地保存的评测结果。通过率需结合任务集、样本数、模型及执行预算一起阅读。"));
  const rows = reportRows(data);
  if (rows.length) {
    const fields = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((key) => rows.some((row) => row[key] !== undefined && typeof row[key] !== "object"));
    const table = element("table", "report-table");
    const head = element("thead");
    const headRow = element("tr");
    fields.forEach((key) => headRow.append(element("th", "", columnLabels[key] || key)));
    head.append(headRow);
    const body = element("tbody");
    for (const row of rows) {
      const tr = element("tr");
      fields.forEach((key) => {
        let value = row[key] ?? "—";
        if (typeof value === "number" && key.includes("rate")) value = `${(value * 100).toFixed(1)}%`;
        else if (typeof value === "number" && !Number.isInteger(value)) value = value.toFixed(2);
        tr.append(element("td", "", value));
      });
      body.append(tr);
    }
    table.append(head, body);
    box.append(table);
  } else box.append(element("p", "report-description", "该报告未包含可识别的汇总表，完整结果见下方。"));
  const raw = rawDetails(data, "查看完整评测报告", "report-raw");
  raw.open = !rows.length;
  box.append(raw);
}

async function loadReports() {
  const reports = asList(await api("/reports"), ["reports", "items"]);
  $("report-count").textContent = reports.length;
  const box = $("report-list");
  box.replaceChildren();
  if (!reports.length) { box.append(element("p", "report-description", "暂无评测报告。")); return; }
  for (const report of reports) {
    const name = typeof report === "string" ? report : report.name || report.filename || report.id;
    const button = element("button", `report-item ${state.report === name ? "active" : ""}`);
    button.dataset.name = name;
    button.append(element("strong", "", report.title || name), element("small", "", dateText(report.created_at || report.modified_at || report.timestamp)));
    button.addEventListener("click", () => openReport(report).catch(showError));
    box.append(button);
  }
  if (!state.report) await openReport(reports[0]);
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
document.querySelectorAll(".result-tab").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".result-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
  document.querySelectorAll(".result-content").forEach((panel) => panel.classList.add("hidden"));
  $(`${button.dataset.result}-result`).classList.remove("hidden");
}));
$("dismiss-error").addEventListener("click", () => $("error-banner").classList.add("hidden"));
$("start-run").addEventListener("click", startRun);
$("task-picker").addEventListener("change", (event) => {
  const task = state.tasks.find((entry) => taskId(entry) === event.target.value);
  if (task) selectTask(task).catch(showError);
});
$("refresh-history").addEventListener("click", () => loadRuns().then(() => toast("运行记录已刷新。")).catch(showError));
$("refresh-reports").addEventListener("click", () => loadReports().then(() => toast("评测报告已刷新。")).catch(showError));
window.addEventListener("beforeunload", stopPolling);

async function initialize() {
  const results = await Promise.allSettled([loadConfig(), api("/tasks"), loadRuns()]);
  results.forEach((result) => { if (result.status === "rejected") showError(result.reason); });
  if (results[1].status === "fulfilled") {
    state.tasks = asList(results[1].value, ["tasks", "items"]);
    renderTasks();
    if (state.tasks.length) await selectTask(state.tasks[0]);
  }
  // Repaint after task metadata arrives so history titles can be resolved.
  if (results[2].status === "fulfilled" && state.runs.length) await loadRuns();
}
initialize().catch(showError);

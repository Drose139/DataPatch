# 聚焦上下文中的关系检查

`context.py` 现在会为已选输入附上 `relationship_checks`：用真实只读查询回答“这个键是否重复、是否为空、是否能找到父表记录”。它给 Agent 关联证据，不生成修复 SQL，也不自动决定哪条路径具有业务权威。本轮实现已整合到冻结核心 `13a729eefb5907437bda7dfdc215c44fb73593e2a59c6eef730b9e1f3c2775ba`。

## 输入从哪里来

入口是 `src/datapatch/context.py::build_task_context()`。新建目标时，检查对象来自已选择的 `candidate_sources`；修复已有目标时，来自有限上游中选出的 staging 模型。最多取 6 个模型，通过模型名精确定位实际数据库关系，仅查询这些关系的列元数据和数据。

`_relationship_checks(database, models)` 使用 `duckdb.connect(..., read_only=True)`。只有不同输入上**同名、同类型、以 `_id` 结尾的列**才参与比较。没有数据库时直接返回不可用，不创建文件；同名关系无法唯一定位时跳过并说明。参考解法、检查脚本和隐藏验收都不是输入。

先为共享列统计行数、NULL 行数、非 NULL 唯一键数、重复键组数和重复多出的行数。父侧至少存在一个非 NULL 键且非 NULL 键唯一、子侧存在重复键时，才提出 `many_to_one_candidate`，即“多对一候选”；父侧 NULL 另行报告。这里尚未识别复合键、异名键或一对一关系。

## 输出怎么读

| 字段 | 含义 |
|---|---|
| `available` | 是否成功取得相关关系元数据；不代表业务检查通过。 |
| `key_profiles` | 每个表／列的行数、NULL、唯一键和重复统计。`duplicate_excess_rows` 是每个非 NULL 重复组中多于第一行的数量之和。 |
| `relationships` | 子表和父表的实际表／列名、父侧非 NULL 唯一性、两侧 NULL、已匹配／非 NULL 未匹配行数、未匹配键数及少量例子。 |
| `limits`、`queries_executed` | 本次剖析的固定限制和实际 SQL 数量。 |
| `truncated`、`error` | 关系、画像或上下文被裁剪，以及查询失败／中断情况。部分证据不能当作完整检查。 |
| `note` | 明确统计范围为完整当前输入，尚未应用工单中的业务过滤。 |

NULL 与孤儿键是两种问题。`child_null_rows=0` 仍可能有 `unmatched_non_null_rows>0`：字符串或数字确实存在，但在父表中找不到对应记录。

## 查询和字符预算

| 限制 | 上限 |
|---|---:|
| 输入模型 | 6 |
| 共享 ID 列画像 | 12 |
| 多对一候选关系 | 6 |
| 每条关系的孤儿键样本 | 3，样本键文本最多 120 字符 |
| 关系剖析 SQL | 19：1 次列元数据＋最多 12 次画像＋6 次关系统计 |
| 每条 SQL | 设置 2 秒中断定时器；失败时保留已取得的部分证据与错误 |
| 整份任务上下文 | 共用 24,000 个 JSON 字符 |

19 次只约束这个关系剖析函数，不是整个 Agent 的工具查询总量。它不扫描无关业务表；精确计数仍需读取所选关系中的相关列。

`_finish()` 把关系证据纳入原有字符预算。超限时先裁 schema、lineage 和候选 SQL，随后可裁关系及键画像；README 和目标 SQL 优先保留，极端超限也会明确标记它们的截断。未匹配最多的关系优先保留，避免裁剪首先隐藏异常。字符数与模型 Token 数仍分别计算。

## 为什么 15、13、18 与有效事实中的 12 不矛盾

真实产品工程的初始只读上下文选择四个 qualified staging 模型，关系剖析执行 12 次 SQL；当次完整上下文为 21,774 字符。统计如下：

| 完整输入上的候选关系 | 子侧非 NULL 行 | 未匹配行／键 |
|---|---:|---:|
| 订单明细 `order_id` → 订单 `order_id` | 3576 | 18／18 |
| 订单明细 `product_id` → 产品 `product_id` | 3576 | 15／15 |
| 订单明细 `variant_id` → 变体 `variant_id` | 3576 | 0／0 |
| 变体 `product_id` → 产品 `product_id` | 1266 | 13／13 |

所以不能仅因为“明细的变体键全部匹配”，就宣布整张变体表的产品归属完整。它仍有 13 个产品孤儿键；订单表关联也有 18 个孤儿订单键。这些都是完整输入的边界。

工单的销售指标先关联有效订单、按公开状态集合排除订单，范围已经改变。该有效子集有 **12 条**孤儿明细产品键，贡献 **20 件、2482.8968 收入**；这 12 条均可通过唯一变体关联到现有产品，其他 2961 条明细的两条产品路径一致。完整表的 15 条不能直接替代有效子集的 12 条，完整变体表的 13 个孤儿也不能被隐去。逐层只读 SQL 与结果保留在 [历史问题诊断](PUBLIC_REMAINING_ISSUE.md)。

“父键唯一”只证明连接不会因父表该键重复而放大事实，不证明该键更可信。若直接产品键和变体产品键都合法却相互冲突，还需要业务优先级；若变体有多个归属或目标不存在，也不能随便挑一行。

## 定位代码并看一个小例子

按以下顺序阅读即可：

1. `build_task_context()`：找到创建分支和已有目标分支传入的模型名。
2. `_relationship_checks()`：看共享列筛选、`profiles`、候选方向和 `NOT EXISTS` 孤儿查询；对应的固定限制在文件顶部 `MAX_RELATION_*`。
3. `_finish()`：看预算裁剪与 `truncated_sections`。
4. `tests/test_context.py`：从 `test_selected_input_relationships_expose_nonnull_orphans_and_complete_alternative` 看一个实际 DuckDB 反例；其余新增测试检查重复父键、固定查询上限、缺失数据库及共享字符预算。

假设父表 `entity_id` 为 A、B，子表为 A、A、Z、NULL：父侧非 NULL 键唯一，子侧有重复 A，因此构成多对一候选。结果应分别说明匹配 2 行、非 NULL 孤儿 Z 为 1 行、NULL 为 1 行。关键查询形状是：

```sql
SELECT c.entity_id, COUNT(*) AS rows
FROM child c
WHERE c.entity_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM parent p WHERE p.entity_id = c.entity_id
  )
GROUP BY c.entity_id;
```

这里会返回 Z，不能靠 `COALESCE(entity_id, ...)` 修复，因为 Z 并非 NULL。后续应确认合法归属、保持有效事实金额／数量，或明确报告无法归属的事实。剖析负责暴露问题，修复策略和最终独立验收分别承担后续判断。

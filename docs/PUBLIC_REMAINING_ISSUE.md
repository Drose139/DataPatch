# 公开商品题剩余问题：只读数据对账

## 后续修复进展：历史诊断仍保留

2026-10-26，用户新的“全部修好”要求已触发继续修复。成品 SQL 采用 **`direct_valid → unambiguous_variant_valid`**：直接产品键能匹配维表时保留，否则仅回退到无歧义且能关联现有产品的变体路径。它处理非 NULL 孤儿键，没有无条件用变体覆盖所有明细。

该商品成品在新建案例的原始公开 pytest 中已实测 **11/11 通过**，记录见 [成品验收报告](../results/acceptance/public_fixes_20261026.json)。其余三个成品也均通过原始验收：退款13/13、客户15/15、库存12/12；成品合计4/4。这个成品验收与自主 Agent 的历史成绩分别记录，未覆盖原商品 Agent 的 8/11 或首轮 3/4。

后续真实Flash定点确认v42仍7/11；从该候选继续并明确项目业务契约的v43已11/11通过，4次调用估算$0.021761。两次共估算$0.098021，未超过合计$0.125预算。它属于契约辅助修复，见 [RESULTS.md](RESULTS.md) 与 [契约说明](PUBLIC_CONTRACTS.md)。下文“没有第三轮／停止调用”等文字描述原诊断完成时的历史范围，不表示用户后来授权继续修复后永久停止所有模型调用。新检查能力见 [关系剖析说明](RELATIONSHIP_CHECKS.md)。

## 原第二轮 Agent 的离线诊断

第二轮商品题最终仍为 **8 passed、3 failed（8/11）**，目标构建成功，Agent 的 `stop_reason=model_finished`。本页是运行结束后的离线诊断，没有新模型调用、没有第三轮、没有重新执行验收，也没有手工修改 SQL 或数据来覆盖 Agent 成绩。最终汇总仍见 [RESULTS.md](RESULTS.md)。

已定位：**12 条有效订单明细含非 NULL 的孤儿 product_id**，合计 **20.00 件、2482.8968 收入**。这些行在原始数据中已经存在，qualified staging 保留了它们；最终模型按明细 product_id 汇总，再从产品主表左连接销售，导致这部分销售没有挂到任何输出产品。此差额不是本次状态 TRIM 引起的。

## 数据与执行边界

本机数据库：`external/native-cases/product-v41-flash-r2/database/retail.duckdb`。

模型：`external/native-cases/product-v41-flash-r2/project/models/marts/product/fct_product_metrics.sql`。公开要求位于同一 case 的 `instruction.md`。本页仅读取这些公开输入、staging SQL 和数据库，没有读取参考解法或 `test_outputs` 断言。

所有下列查询均通过 `duckdb.connect(..., read_only=True)` 执行。复现时在项目根目录使用 `.venv` 的 Python，连接方式如下；将一段 SQL 放入 `sql`，调用 `connection.execute(sql).fetchall()`：

```python
from pathlib import Path
import duckdb
database = Path("external/native-cases/product-v41-flash-r2/database/retail.duckdb")
connection = duckdb.connect(str(database), read_only=True)
```

## 1. 先证明差额在哪一层出现

```sql
SELECT 'raw_valid_lines' AS layer, COUNT(*) AS rows,
       SUM(l.quantity_ordered) AS units, SUM(l.line_total) AS revenue
FROM "ORDERS"."ORDER_LINES" l
JOIN "ORDERS"."ORDERS" o ON l.order_id = o.order_id
WHERE o.status NOT IN ('CANCELLED', 'RETURNED', 'FAILED')
UNION ALL
SELECT 'qualified_valid_lines', COUNT(*), SUM(l.quantity_ordered), SUM(l.line_total)
FROM main.stg_orders__order_lines l
JOIN main.stg_orders__orders o ON l.order_id = o.order_id
WHERE o.status NOT IN ('CANCELLED', 'RETURNED', 'FAILED')
UNION ALL
SELECT 'final_products', COUNT(*), SUM(units_sold), SUM(product_revenue)
FROM main.fct_product_metrics;
```

| 层次 | 行数及粒度 | units | revenue |
|---|---|---:|---:|
| 原始有效订单明细 | 2973 条明细 | 5480.00 | 596282.9608 |
| qualified staging 有效明细 | 2973 条明细 | 5480.00 | 596282.9608 |
| 最终产品表 | 487 个产品 | 5460.00 | 593800.0640 |

前两层还分别包含 1669 个订单、475 个明细 product_id。原始产品主表、qualified 产品源和最终表均为 **487 行、487 个唯一非 NULL 产品键**。因此，“全部产品都输出”可以成立，同时“全部有效销售都归属”仍然失败。

状态转换另作独立排除：

```sql
SELECT COUNT(*) AS orders,
  COUNT(*) FILTER (WHERE status IS DISTINCT FROM TRIM(status)) AS status_trim_changes,
  COUNT(*) FILTER (WHERE
    (status NOT IN ('CANCELLED','RETURNED','FAILED')) IS DISTINCT FROM
    (TRIM(status) NOT IN ('CANCELLED','RETURNED','FAILED'))) AS eligibility_changes
FROM "ORDERS"."ORDERS";
```

实际结果：`orders=2037, status_trim_changes=0, eligibility_changes=0`。原始订单、订单明细、产品主表的主键均唯一且非 NULL；订单关联键和产品键也没有因 TRIM 改变。这里不把首轮额外 `UPPER()` 的问题套到第二轮差额上。

## 2. 用反连接精确找出丢失事实

```sql
WITH valid_lines AS (
  SELECT l.* FROM main.stg_orders__order_lines l
  JOIN main.stg_orders__orders o ON l.order_id = o.order_id
  WHERE o.status NOT IN ('CANCELLED','RETURNED','FAILED')
)
SELECT CASE
  WHEN l.product_id IS NULL THEN 'null_product_id'
  WHEN NOT EXISTS (SELECT 1 FROM main.stg_product__products p
                   WHERE p.product_id = l.product_id)
    THEN 'orphan_product_id'
  ELSE 'matched_product_id' END AS kind,
  COUNT(*) AS line_rows, COUNT(DISTINCT l.product_id) AS product_keys,
  SUM(l.quantity_ordered) AS units, SUM(l.line_total) AS revenue
FROM valid_lines l GROUP BY 1 ORDER BY 1;
```

| kind | 明细行 | 产品键 | units | revenue |
|---|---:|---:|---:|---:|
| matched_product_id | 2961 | 463 | 5460.00 | 593800.0640 |
| orphan_product_id | 12 | 12 | 20.00 | 2482.8968 |

没有 NULL 产品键组。对原始 `ORDERS.ORDER_LINES` 与 `PRODUCT.PRODUCTS` 做相同反连接，也得到这 12 条及相同金额，所以孤儿键并非 staging 新制造。

最终 SQL 的 `valid_order_lines` 仅检查 `ol.product_id IS NOT NULL`；这 12 条非 NULL 记录仍进入 `sales GROUP BY product_id`。之后 `FROM products p LEFT JOIN sales s ON p.product_id=s.product_id`，以维表为起点的连接没有对应键，12 组销售便无法进入输出。只检查 NULL、输出行数和“没有 fan-out”都发现不了这个缺口。

## 3. 变体关系是否真的可以还原

`main.stg_product__product_variants` 实际为 **1266 行、1266 个唯一 variant_id**，variant_id 和 product_id 均无 NULL。先核对明细产品键与变体所属产品键：

```sql
WITH valid_lines AS (
  SELECT l.* FROM main.stg_orders__order_lines l
  JOIN main.stg_orders__orders o ON l.order_id=o.order_id
  WHERE o.status NOT IN ('CANCELLED','RETURNED','FAILED')
)
SELECT CASE WHEN v.variant_id IS NULL THEN 'missing_variant'
            WHEN l.product_id IS NOT DISTINCT FROM v.product_id THEN 'same_product'
            ELSE 'different_product' END AS kind,
       COUNT(*) AS line_rows, SUM(l.quantity_ordered) AS units,
       SUM(l.line_total) AS revenue,
       COUNT(*) FILTER (WHERE p.product_id IS NOT NULL) AS variant_product_in_dimension
FROM valid_lines l
LEFT JOIN main.stg_product__product_variants v ON l.variant_id=v.variant_id
LEFT JOIN main.stg_product__products p ON v.product_id=p.product_id
GROUP BY 1 ORDER BY 1;
```

| kind | 明细行 | units | revenue | 变体指向现有产品的明细行 |
|---|---:|---:|---:|---:|
| same_product | 2961 | 5460.00 | 593800.0640 | 2961 |
| different_product | 12 | 20.00 | 2482.8968 | 12 |

没有 missing_variant 组。12 条孤儿明细均能通过唯一 variant_id 找到现有产品；例如：

| 明细 product_id | 变体指向的真实 product_id | units | revenue |
|---|---|---:|---:|
| ORPHAN-PROD-1459 | 37d567d9-39ab-4e77-967e-a5d176cc5032 | 1.00 | 111.5300 |
| ORPHAN-PROD-1945 | d0596d61-e99d-4e7e-93bb-57c537e319ec | 1.00 | 107.2200 |
| ORPHAN-PROD-2028 | 8cf54f68-236f-4154-a006-f677f3ff9685 | 2.00 | 380.1800 |

只读诊断进一步按 `v.product_id` 聚合销售，再左连接 487 个产品，观察归属变化：

```sql
WITH mapped_sales AS (
 SELECT v.product_id, COUNT(DISTINCT l.order_id) AS total_orders,
        SUM(l.quantity_ordered) AS units_sold, SUM(l.line_total) AS product_revenue
 FROM main.stg_orders__order_lines l
 JOIN main.stg_orders__orders o ON l.order_id=o.order_id
 JOIN main.stg_product__product_variants v ON l.variant_id=v.variant_id
 WHERE o.status NOT IN ('CANCELLED','RETURNED','FAILED') GROUP BY v.product_id
), comparison AS (
 SELECT p.product_id, COALESCE(s.total_orders,0) AS diagnostic_orders,
        COALESCE(s.units_sold,0) AS diagnostic_units,
        COALESCE(s.product_revenue,0) AS diagnostic_revenue,
        f.total_orders AS actual_orders, f.units_sold AS actual_units,
        f.product_revenue AS actual_revenue
 FROM main.stg_product__products p
 LEFT JOIN mapped_sales s ON p.product_id=s.product_id
 LEFT JOIN main.fct_product_metrics f ON p.product_id=f.product_id
)
SELECT COUNT(*) AS products,
 SUM(actual_orders) AS actual_product_order_counts,
 SUM(diagnostic_orders) AS diagnostic_product_order_counts,
 SUM(actual_units) AS actual_units, SUM(diagnostic_units) AS diagnostic_units,
 SUM(actual_revenue) AS actual_revenue, SUM(diagnostic_revenue) AS diagnostic_revenue,
 COUNT(*) FILTER (WHERE actual_units IS DISTINCT FROM diagnostic_units
                  OR actual_revenue IS DISTINCT FROM diagnostic_revenue
                  OR actual_orders IS DISTINCT FROM diagnostic_orders) AS products_changed
FROM comparison;
```

实际结果：仍为 **487 个产品**，12 个产品的指标变化；各产品订单数之和从 **2913 → 2925**，销量从 **5460 → 5480**，收入从 **593800.0640 → 596282.9608**。产品订单数之和与全局去重订单数是不同粒度，不能混为一个指标。这只是 SELECT/CTE 的数据归属诊断，没有物化为新模型，也没有提交或重新评分。

## 应该怎样理解这个失败

这是公开输入中的真实外键不一致边界：同一明细的 product_id 与 variant_id 指向的产品矛盾。模型把明细 product_id 直接当作完整可信键，只使用变体表统计数量，因而漏掉了可关联的有效销售。源金额本身没有在 staging 丢失，损失发生在销售事实进入产品汇总的关联边界。

公开工单要求探索产品、变体、订单及明细之间的关系，保留指定状态之外的有效销售；但没有完整写出“两个产品键冲突时谁优先”的业务规则。因此可以证明当前表少了哪些有效事实，也可以证明变体路径在本次数据上存在唯一、可还原的归属；不能据此宣称任意企业数据都应无条件以变体覆盖明细。需要明确可信键、冲突处理和无法归属事实的报告方式。`COALESCE(明细产品键, 变体产品键)` 也不足以解决这些非 NULL 孤儿键。

用户需要掌握三个检查：维表产品覆盖、有效销售金额/数量保全、冲突键与孤儿事实计数。它们应分别验证；一张表行数正确，并不表示销售事实完整。本页没有映射或猜测三个失败断言，也没有取得新的通过成绩。第二轮仍 **0/1、8/11**；首轮四题仍 **3/4**，失败和最终 Agent 补丁原样保留，不开展第三轮。

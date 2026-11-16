# 数据变化证据

`evidence.capture_output()` 只读查询实际 DuckDB 表，记录 schema、全表行数、调用者声明的键校验、最多前 60 列的 NULL/非有限值计数，以及最多 5000 条行记录和 10 条预览。它不推断业务主键，不访问期望结果或参考代码，也不修改数据库。

`compare_outputs()` 区分新增列、删除列、类型变化与行数变化。只有两边都可读取、明确声明了相同键、键的类型一致、全表键唯一且非 NULL、两份行快照均完整时，才给出全量 added/removed/changed/unchanged 数量。各类差异最多展示 5 条样本。changed 只比较双方共有且类型相同的非键列；新增、删除、类型变化的列单独出现在 schema 区域，不混成旧值变化。

键无效、未声明或超过快照上限时，`keyed_diff.supported=false`，数量为 `null`，不会假装是零变化。缺少基线时也不会把所有现存行说成新增；schema 不可比较、行数 delta 为 `null`。全表行数和键校验不受 5000 行快照上限影响。

为输出合法 JSON，NaN、正负 Infinity 转为同名字符串，日期为 ISO 格式，Decimal 为保留精度的字符串。比较不四舍五入。`duplicate_key_rows` 表示属于重复键分组的全部行数，而不是超出唯一约束的多余行数。

**差异不是正确性证明。** 修复前模型可能本来就错，修复也可能有意改变全表。service 应另行记录 `initial_build_success`、`final_build_success`，在最终构建失败时明确 after 数据可能陈旧；此模块自己不判断构建新鲜度。公开业务契约和最终独立验收仍各自保留。

机制来源与采用理由见 [RESEARCH_DATA.md](RESEARCH_DATA.md)。测试使用真实临时 DuckDB 表覆盖同样行数下的新增/删除/值更改、重复/NULL 键、schema 变化、缺失基线、非有限数值与截断，不使用模型调用。

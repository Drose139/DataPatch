# DataPatch 实际模型评测 · final_acceptance_20261025

数据集：datapatch-synthetic-v1

自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明

状态：completed；记录 2/2 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1/1 | 100.0% | 未做重复实验 | 39.53 | 1722 | 0.000777 |
| verified | 1/1 | 100.0% | 未做重复实验 | 85.48 | 20401 | 0.007141 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| refund_reconciliation_holdout | baseline | 0 | True | dc4496b4-581d-4bc2-aeb4-313f1da328ef |
| refund_reconciliation_holdout | verified | 0 | True | 42fdb20f-0177-4f84-a529-f29b5b6803da |

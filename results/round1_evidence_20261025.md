# DataPatch 实际模型对照评测

数据集：datapatch-synthetic-v1

自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明

状态：completed；记录 2/2 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 2/2 | 100.0% | 未做重复实验 | 89.22 | 94451 | 0.031352 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| refund_reconciliation_holdout | verified | 0 | True | ec548a48-0875-45ec-a4aa-6a257e7dd467 |
| build_customer_ltv_holdout | verified | 0 | True | c91744f8-3379-4f9b-92ce-455ad2c7e585 |

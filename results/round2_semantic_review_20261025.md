# DataPatch 实际模型对照评测

数据集：datapatch-synthetic-v1

自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明

状态：completed；记录 6/6 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 5/6 | 83.3% | 未做重复实验 | 135.96 | 481924 | 0.158985 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| revenue_fanout_holdout | verified | 0 | True | 241bd5e4-559a-431c-a096-af8f02c812af |
| refund_reconciliation_holdout | verified | 0 | True | 019f6fbd-7d8b-4c7e-9f2e-62eff59a0c40 |
| local_day_boundary_holdout | verified | 0 | True | f30c5cf2-ceaf-4d76-a7c0-9f7a0ed5fc83 |
| repeat_customer_identity_holdout | verified | 0 | True | 802ebb43-3874-42e1-97d7-62330e2e28ba |
| incremental_replay_holdout | verified | 0 | False | 8de016ec-37b4-42d4-a542-b144092f6b12 |
| build_customer_ltv_holdout | verified | 0 | True | d484b837-c3c8-45ed-90f8-bf72288688e4 |

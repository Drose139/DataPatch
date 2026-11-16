# DataPatch 实际模型对照评测

数据集：datapatch-synthetic-v1

自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明

状态：completed；记录 6/6 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 6/6 | 100.0% | 未做重复实验 | 102.42 | 214452 | 0.071045 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| revenue_fanout_holdout | verified | 0 | True | d8a346b8-a598-4838-b382-a08c13bad194 |
| refund_reconciliation_holdout | verified | 0 | True | 9d99a96d-a3a4-48c1-bbff-c8b04dd4d73a |
| local_day_boundary_holdout | verified | 0 | True | f287392e-10ca-4a8c-bf92-de28cd8cbef3 |
| repeat_customer_identity_holdout | verified | 0 | True | b7cd405a-de9c-4c45-88c6-943cee62ab67 |
| incremental_replay_holdout | verified | 0 | True | f25a44e5-9110-442a-ae8b-044f9e854f06 |
| build_customer_ltv_holdout | verified | 0 | True | c54af6cb-1074-41d3-b7fd-5d00628d6bce |

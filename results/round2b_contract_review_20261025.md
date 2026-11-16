# DataPatch 实际模型对照评测

数据集：datapatch-synthetic-v1

自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明

状态：completed；记录 6/6 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| verified | 6/6 | 100.0% | 未做重复实验 | 96.59 | 191325 | 0.063835 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| refund_reconciliation_holdout | verified | 0 | True | e9ed927d-921c-48ac-a521-e223afa31dde |
| revenue_fanout_holdout | verified | 0 | True | 20e2e135-555e-415e-8cbb-6414f4da2d56 |
| local_day_boundary_holdout | verified | 0 | True | 6608f7d5-bb49-4d3b-87d0-8b561ba470bc |
| repeat_customer_identity_holdout | verified | 0 | True | 4c28ad78-60aa-4fc3-b91d-ebadf3b169e8 |
| build_customer_ltv_holdout | verified | 0 | True | a5052617-234d-40f8-b324-3725acf5c005 |
| incremental_replay_holdout | verified | 0 | True | 5872e622-7edd-4130-8ce5-e27fa446e358 |

# DataPatch 实际模型对照评测

数据集：datapatch-synthetic-v1

自建合成零售数据；holdout 是相同问题类型的新数据，非第三方榜单或未知任务泛化证明

状态：completed；记录 54/54 次实际运行。

| 模式 | 成功/运行 | 成功率 | 三次/多次全成功 | 平均秒数 | Tokens | 估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| react | 18/18 | 100.0% | 1.0 | 91.89 | 570663 | 0.193171 |
| context | 17/18 | 94.4% | 0.8333 | 85.46 | 600345 | 0.200543 |
| verified | 17/18 | 94.4% | 0.8333 | 103.01 | 911824 | 0.296492 |

费用为配置单价估算，实际账单以 API 服务商为准。小样本区间与原始失败保留在 JSON 中；没有证据时不宣称统计显著提升。

## 逐次运行

| 任务 | 模式 | 重复 | 成功 | Run ID |
|---|---|---:|---|---|
| revenue_fanout_holdout | react | 0 | True | db0326c8-5201-42d5-b06f-2e844f949b8c |
| revenue_fanout_holdout | context | 0 | True | 99583153-85a6-4b4e-939f-a1aee12b0969 |
| revenue_fanout_holdout | verified | 0 | True | b36450a9-4ea9-47f8-8a03-85e3cdab916f |
| refund_reconciliation_holdout | context | 0 | False | c8f7420b-86a5-48cc-8594-da441698f7fa |
| refund_reconciliation_holdout | react | 0 | True | 7b5f116e-5996-44e8-8f2b-272705d70e3b |
| refund_reconciliation_holdout | verified | 0 | True | 9ac46785-8dcf-43e5-8369-40606471a7cf |
| local_day_boundary_holdout | react | 0 | True | 4001314f-07d2-4ac8-85d0-25bd64b429fd |
| local_day_boundary_holdout | context | 0 | True | 141e7f0e-890e-49a5-ab7a-17e89622aff4 |
| local_day_boundary_holdout | verified | 0 | True | 27db05cf-36de-424f-8ac4-22e521608b54 |
| repeat_customer_identity_holdout | context | 0 | True | 8df1e344-4964-4451-8789-95e3d309f3b4 |
| repeat_customer_identity_holdout | react | 0 | True | 296d04e0-c9fc-41f0-8509-1cd998510a6b |
| repeat_customer_identity_holdout | verified | 0 | True | b979a38c-664b-4d82-b381-9435fd3732e9 |
| incremental_replay_holdout | context | 0 | True | 5f3a05a4-add9-4913-8bce-c447a2828a70 |
| incremental_replay_holdout | react | 0 | True | e734a9de-b9a7-4c2b-b028-c0b5b304ce56 |
| incremental_replay_holdout | verified | 0 | True | 7e05e979-c067-4721-8b1b-61e9b95d4440 |
| build_customer_ltv_holdout | react | 0 | True | ca9b0e38-b3d0-41be-9fce-896f8990d0c8 |
| build_customer_ltv_holdout | context | 0 | True | afc0df67-1cfa-4667-8fa3-37522c1013c4 |
| revenue_fanout_holdout | react | 1 | True | dd3170a1-aa61-49a8-8ef5-2fdfb5fd33e5 |
| revenue_fanout_holdout | context | 1 | True | 504c4238-223a-49de-a5b2-d7eaa8c44906 |
| build_customer_ltv_holdout | verified | 0 | False | e8f195a6-4bc7-4483-940c-dbaac4316918 |
| refund_reconciliation_holdout | context | 1 | True | 4f07ab2e-ad23-4f12-9004-30b3efb11bb5 |
| refund_reconciliation_holdout | react | 1 | True | ba7a7e50-7356-49ac-800b-c4242e9dd9c0 |
| revenue_fanout_holdout | verified | 1 | True | 10dc265e-5efe-415c-a285-46ce21d78ecc |
| local_day_boundary_holdout | context | 1 | True | bbf5a066-feca-4958-9071-fd3f8551bc64 |
| refund_reconciliation_holdout | verified | 1 | True | f38df744-e528-4bdc-8cb0-eede856ffc78 |
| local_day_boundary_holdout | react | 1 | True | d78c2400-4bb9-4c34-a246-ac23cffce57e |
| repeat_customer_identity_holdout | react | 1 | True | 06cdcfe6-c6ce-4f89-88df-a52b7107732e |
| repeat_customer_identity_holdout | context | 1 | True | e27717a6-91fa-4943-987e-1d952ba05a8d |
| local_day_boundary_holdout | verified | 1 | True | 0653f027-bc27-4807-9a63-7f32abc136bf |
| repeat_customer_identity_holdout | verified | 1 | True | 4dd3e7b6-6223-467b-a3a8-799a2bad124d |
| incremental_replay_holdout | react | 1 | True | e8f60911-b2f2-4a8c-90d6-fc3c53f88b37 |
| incremental_replay_holdout | context | 1 | True | c13ef34c-3d7e-426c-9b79-69c3cecc0543 |
| build_customer_ltv_holdout | context | 1 | True | 18db22ab-62a9-45c7-a0d1-7d4e05ab4b3b |
| build_customer_ltv_holdout | react | 1 | True | 85654d4c-1c5b-47c1-8ef7-e2a89614f195 |
| incremental_replay_holdout | verified | 1 | True | 074e4db2-910f-468f-b5e0-c16d5fee955f |
| revenue_fanout_holdout | react | 2 | True | 911cfa03-9ef4-4006-aecb-d6c5f7ce7a3e |
| revenue_fanout_holdout | context | 2 | True | 01c95b0e-89cc-4c0f-919c-6d7d642a2ff3 |
| build_customer_ltv_holdout | verified | 1 | True | 7ad5811b-45de-4f90-806e-b02927f4bfd3 |
| revenue_fanout_holdout | verified | 2 | True | 62030ed6-76cf-4f7a-9a53-b35654837683 |
| refund_reconciliation_holdout | react | 2 | True | 50ddce04-a022-40f0-bb13-3d7c09f6206d |
| refund_reconciliation_holdout | context | 2 | True | 82d396db-0733-40fe-8bc5-f936afd893c2 |
| local_day_boundary_holdout | react | 2 | True | 83504b48-0182-43af-80c8-efb8adcf16cb |
| refund_reconciliation_holdout | verified | 2 | True | 9972a48d-1ec7-4a81-a5bc-ea692472f6e7 |
| local_day_boundary_holdout | context | 2 | True | 5402d61c-6d2b-4c8b-9420-61c61ce11202 |
| repeat_customer_identity_holdout | context | 2 | True | 33e6d0be-689c-4842-be92-ad1a57436ad7 |
| repeat_customer_identity_holdout | react | 2 | True | 4ca7b52a-5668-469e-a7da-8d65dc9c747e |
| local_day_boundary_holdout | verified | 2 | True | 5d0cb456-63d7-406c-a8f4-bb756ba816bb |
| repeat_customer_identity_holdout | verified | 2 | True | 0a96f390-87fe-4d07-b0ea-c22c502fcffd |
| incremental_replay_holdout | context | 2 | True | 42005f72-797b-47e8-b4d7-23577c2c199f |
| incremental_replay_holdout | react | 2 | True | feb400d6-006b-4798-8aeb-85feabbbc5e0 |
| build_customer_ltv_holdout | react | 2 | True | 98c3489a-439f-44a3-b039-259a91d2639a |
| build_customer_ltv_holdout | context | 2 | True | f8967625-ba89-45f9-80b2-bac533e236d6 |
| incremental_replay_holdout | verified | 2 | True | 457be74f-201c-4e9a-9538-09802abf6ddc |
| build_customer_ltv_holdout | verified | 2 | True | 3b425a3a-187a-4ada-85d7-4a887da0f439 |

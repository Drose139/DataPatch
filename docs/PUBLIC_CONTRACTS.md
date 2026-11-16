# 公开业务契约与低费用修复

项目可以由调用者提供 `README.md` 和返回违规行的 SQL 检查。它们是项目业务配置，模型可以读取，`Workspace.check_contracts()` 可以执行；最终上游 pytest 仍在工作区之外。

商品案例明确了原工单容易产生歧义的选择：收入取源 `line_total`，有效直接产品键优先，孤儿键可通过无歧义且存在的变体所属产品恢复，销售量与收入必须保全。这个补充来自项目维护者，因此结果标为 **project_public_business_contract**，不能当作未经辅助的盲测。

入口是 `integrations/harbor_agent.py::install_public_contracts()`。它复制根目录 SQL 和短 README 到 case 的 `checks/`，记录原件及复制件 SHA，另写 `solver-instruction.md`，保留原 `instruction.md`。模型写工具只能改 `models/`。相同检查可再次安装，不同内容拒绝覆盖。

```powershell
# 仅准备新案例，不调用模型
.venv/Scripts/python.exe integrations/harbor_agent.py prepare --case external/native-cases/my-product --task dbt-fix-product-metrics
# 以下才会调用付费 Flash；需要时手动执行一次
.venv/Scripts/python.exe integrations/harbor_agent.py run --case external/native-cases/my-product --mode verified --max-steps 4 --budget-usd 0.045 --contracts-dir examples/public_contracts/product
```

历史实际结果：[v43 报告](../results/v43_contract_repair_20261026.json)。它从 v42 的真实失败候选继续修复，目标初始 SHA 为 `5ebd30cffd9e8ac4adb9c38276e3d03732d867f4d56f793435b2722c3dc74222`，没有提供审阅后的正确 SQL。4 次 Flash 调用、62,455 Tokens、估算 $0.021761，结束为 `step_limit`；随后独立目标构建和原上游 11 项测试全部通过。停止原因与补丁验收分别保留。

当前模板为 `product-contract-v2`。离线反例发现未售商品的 NULL 销量或收入会被 SUM 和 SQL 三值逻辑忽略，已加入显式 NULL 拒绝。历史 v43 使用的 v1 文件保留在其 case 和源码归档中，不回改历史结果。

无需 API 的契约集成回归：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_public_contract_checks.py
```

该测试使用真实 `Workspace.check_contracts()`、Jinja ref 展开和 DuckDB，验证正确输出及收入错误、事实丢失、重复/遗漏产品、错误加权和 NULL 指标的反例。检查通过只表示这些已声明条件成立，最终业务验收仍另行执行。

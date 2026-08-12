# 02 · 证据驱动 Gate（契约）

`evaluate_gate_from_evidence(store, uat_report_path, browser_report_path,
issue_ledger_path, test_report_path, service_health)` 自动计算：

open P0/P1（ISSUES.md 解析）；UAT checks 失败数；validator 问题；
Run/Work/Approval/Timer/Branch 终态漂移扫描；Agent Usage 完整率；
Agent 失败账本存在性；storefront 负例+成功例；parallel wall-time 与
终态；工作流必备节点类型（含 model/capability）；anomaly 追问链
（anomaly_id/follow-up/answer/resolved/新版本）；rate limit 覆盖与
拒绝证据；V4 证据诚实性；服务健康；SQLite integrity；测试结果；
浏览器证据（文件存在）；当前模型；训练进程。

输出写 `.eval/v3_uat_v3/gate.json`：
{gate, reasons[], checks[], evidence_hashes{}, evaluated_at,
 evaluator_version, source_commit}。文档只引用，不得人工改写；
任一证据缺失/失败 → BLOCKED_BY_*。

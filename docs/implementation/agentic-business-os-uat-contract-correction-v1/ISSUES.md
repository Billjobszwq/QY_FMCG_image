# ISSUES

| ID | 级别 | 状态 | 摘要 | 关闭证据 |
|---|---|---|---|---|
| UATCC-001 | P0 | CLOSED | 门头必拍可绕过 | lint/submit 契约 + RED-1/2 绿 + UAT V2 负证据（无门头照 409）|
| UATCC-002 | P0 | CLOSED | Agent Usage 无链 | 每次 invoke 建 run/work/evidence；新 Usage 4/4 挂链；历史 12 条追加式 legacy 账本 |
| UATCC-003 | P0 | CLOSED | parallel 伪并行 | 线程池真实并行 + durable 分支 + join all/any/quorum + wall-time 证明 + 重启恢复 |
| UATCC-004 | P0 | CLOSED | UAT 报告无强制校验/fixture 复用 | uat_report_validator + UAT V2 唯一 namespace + inserted 校验 |
| UATCC-005 | P1 | CLOSED | shadow sku_name 全 '?'、口径缺失 | extract_products 读 sku_name + hash + 证据口径分类 + 负样本 + p50/p95；旧报告保留 |
| UATCC-006 | P1 | CLOSED | rate limit 未实现（不得降 P2） | SQLite 持久化限流 9 能力；线上登录 429 实证；9 专项测试 |
| UATCC-007 | P0 | CLOSED | Gate 判定器缺失 | gate_evaluator fail-closed；READY 判定仅在全条件满足时给出 |
| UATCC-008 | P1 | CLOSED | timer 恢复后 ctx 丢失输入/变量 | _restore_ctx 重建 trigger 输入 + transform _vars checkpoint（UAT V2 condition 分支实证） |
| UATCC-009 | P1 | CLOSED | loop body 被 lint 判不可达 | lint 可达性纳入 config.body（UAT V2 全业务流 lint 通过） |
| UATCC-010 | P1 | CLOSED | retry 端点 SimulateBody.get 500 | inputs=body.inputs 修复；UAT V2 重试成功 |
| UATCC-011 | P1 | CLOSED | 报表 versions 端点 _guard 参数冲突 500 | 修复后 UAT V2 报表版本可见 |

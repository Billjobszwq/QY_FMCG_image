# ISSUES — operational-scope-v5-correction-v2

| ID | 级别 | 标题 | 状态 | 证据 |
|---|---|---|---|---|
| OSV52-001 | P1 | Gate 不校验证据文件当前哈希（QA ISSUE-001；negative 断链仍 READY） | CLOSED | freshness 重读重算 manifest（整文件/尺寸/路径安全/JSON 可解析/binding/result_hash 分层）；HASH_DRIFT 阻断码；27 项负例 ALL_BLOCKED |
| OSV52-002 | P1 | 实时 Gate 按 mtime 选择 gate.json（旧 scope 可接管） | CLOSED | 迁移 061 gate_run_v1 append-only Registry；实时端点只读 active；激活 CAS+人工批准+协议防接管；8 项 API 测试 |
| OSV52-003 | P1 | Import Center URL 视图不随刷新/直链恢复（QA ISSUE-002） | CLOSED | ?view= 单一事实源；未知规范化 replace；页签 PUSH 同步；四视图×四视口三方一致断言 |
| OSV52-004 | P2 | 测试返回非 None 产生 warning（QA ISSUE-003） | CLOSED | 唯一违规测试改断言+helper；runner -W error::PytestReturnNotNoneWarning；AST 扫描确认零残留 |
| OSV52-005 | P2 | 首页无语义 H1（QA ISSUE-004） | CLOSED | 加载中分支亦有 H1；浏览器断言 home_unique_h1_focus（唯一 H1 + 焦点 H1） |
| OSV51-013 | P2 | set_business_run_status SELECT-then-UPDATE | CLOSED | 实证 1500 轮 1301 覆盖 → 条件 UPDATE/CAS；修复后 1500/1500 恰一赢家 0 覆盖；终态不可回退契约 + 7 测试 |
| OSV52-007 | P2 | vendor-maplibre 构建块约 949KB（gzip 248KB） | OPEN（登记，本轮不重构） | QA 其他风险；性能债务，按任务书只登记 |

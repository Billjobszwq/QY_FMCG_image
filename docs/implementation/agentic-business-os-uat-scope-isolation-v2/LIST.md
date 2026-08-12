# LIST · 工作项账本 · UAT Scope Isolation V2

| ID | 阶段 | 事项 | 状态 | 证据 |
|---|---|---|---|---|
| SI2-T0-1 | T0 | 现场只读审计 | DONE | 00-LIVE-AUDIT.md |
| SI2-T0-2 | T0 | DB 备份 + integrity | DONE | platform_pre_scope_v2_20260812202343.sqlite（sha256=7d65b1ce…） |
| SI2-T0-3 | T0 | Gate 降级投影 | DONE | .eval/uat_scope_v2/gate.json |
| SI2-T0-4 | T0 | 治理文档 13 件 | DONE | 本目录 |
| SI2-T1-1 | T1 | 红测试 22 项（首跑全红→全绿） | DONE | tests/platform/test_si2_scope_isolation.py |
| SI2-T2-1 | T2 | src/platform/scope.py | DONE | 013efe3a |
| SI2-T3-1 | T3 | 迁移 051/052/053 + backfill | DONE | 9548cc30 |
| SI2-T4-1 | T4 | 全 Domain 默认 operational | DONE | 013efe3a |
| SI2-T5-1 | T5 | 测试与证据中心 | DONE | 52b9069b |
| SI2-T6-1 | T6 | Gate 2.1（26 检查 + 12/12 负例） | DONE | ea6ea086 |
| SI2-T7-1 | T7 | 浏览器语义证据（10 pages） | DONE | .eval/uat_scope_v2/browser/ |
| SI2-T8-1 | T8 | UAT V4 预演 31/31 | DONE | fbeac0f3 |
| SI2-T9-1 | T9 | 前端拆包（gzip 818KB→72KB）+ 警告收口 | DONE | b38d9421 |
| SI2-T10-1 | T10 | 回归 + 负例 + 最终报告 | DONE | FINAL-REPORT.md |

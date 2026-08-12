# STATUS · Operational Scope V4

当前 Gate：`BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE`（机器投影
`.eval/scope_v4/gate.json`；实时 /control/gate 可见）。Scope V3 的
READY 已因 HEAD 前进自然 STALE，且覆盖面不足，不作为任何放行依据。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 现场审计 + 备份 + Gate 降级 + 治理目录 | DONE |
| T1 | 红测试（全问题复现） | TODO |
| T2 | IAM 测试身份生命周期 | TODO |
| T3 | BI effective operational 口径 | TODO |
| T4 | Finance/Usage 运营上下文 | TODO |
| T5 | Scope Registry 语义升级 | TODO |
| T6 | Gate 3.1 + 负例 | TODO |
| T7 | UAT V6 | TODO |
| T8 | UI/UX + 12 页浏览器验收 | TODO |
| T9 | 性能/安全 + 全量回归 | TODO |
| T10 | FINAL-REPORT + handbook | TODO |

放行条件：指令第十七节全部硬门槛通过后才允许机器给出
READY_FOR_REAL_DATA_UAT；任何一项未满足写明确 BLOCKED。
本轮不写 ACCEPTED/COMPLETE/PRODUCTION_READY。

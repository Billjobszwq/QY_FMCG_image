# STATUS · Operational Scope V4

当前 Gate：以 `.eval/scope_v4/gate.json` 机器文件为准（Gate 3.1，
34 检查 evidence-driven + DB fingerprint freshness；
`/api/v1/control/gate` 实时复评确认）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 现场审计（外部 commits 审计）+ 备份 + Gate 降级 + 治理目录 | DONE（6121353f） |
| T1 | 红测试 15 项（P0-001…P2-002 复现） | DONE（fe7a543c） |
| T2 | IAM 测试身份生命周期（迁移 057） | DONE（9fd80c7c） |
| T3 | BI effective operational（迁移 058 + data-products 对账） | DONE（9fd80c7c） |
| T4 | Finance/Usage 运营上下文（默认值清除/invoice provenance） | DONE（9fd80c7c/b1dded1c） |
| T5 | Registry 语义升级 + live 历史收敛（r20–r23，全审计） | DONE（9fd80c7c/705024ec/a4fb3f7f） |
| T6 | Gate 3.1（新检查 + 22 负例） | DONE（a4fb3f7f+收尾） |
| T7 | UAT V6（57/57，ids 30/30） | DONE（b1dded1c） |
| T8 | UI/UX（浮层/IAM 列表）+ 12 页浏览器验收 30/30 | DONE（a4fb3f7f） |
| T9 | 性能/安全/回归（1447 passed/host MPS 6） | DONE |
| T10 | FINAL-REPORT（47 项）+ handbook | DONE |

硬门槛复核（指令第十七节）：active UAT principals=0；operational
memberships=0；archived 登录成功=0；UAT metric/dashboard/report
operational=0；BI 计数=运营 API；Finance 默认 fixture=0；invoice
fixture=0；运营页 fixture token=0；terminal drift=0；Registry 语义
100%；V6 IDs 100%；Gate 负例全阻断；SQLite ok；hermetic 0 failed；
host MPS 6；typecheck/build 干净；console 0；四视口无溢出无遮挡；
四服务健康；production=prod_v4_best_r1；训练进程=0；worktree 干净。

机器 Gate = READY_FOR_REAL_DATA_UAT（仅限机器评估结论；真实数据
UAT 与人工验收由用户执行，此前不写 ACCEPTED/COMPLETE/
PRODUCTION_READY）。

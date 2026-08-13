# STATUS · Operational Scope V5

当前 Gate：以 `.eval/scope_v5/gate.json` 机器文件为准（Gate 3.2，
evaluator_version=3.2.0；`/api/v1/control/gate` 实时复评确认）。

| 阶段 | 内容 | 状态 |
|---|---|---|
| T0 | 现场审计 + 备份 + Gate 降级 + 治理目录 | DONE |
| T1 | 红测试 30 类（OSV5-001…012 复现） | DONE |
| T2 | Import 作用域模型（迁移 059/多客户关联/创建规则） | DONE |
| T3 | Import API IAM 接入（权限/作用域/DTO/脱敏） | DONE |
| T4 | 可执行 Scope Registry（类型化/validator/scanner+archiver 派生） | DONE |
| T5 | 历史 20 条纠偏（classification plan/quarantine/审计） | DONE |
| T6 | Gate 3.2（18 新检查 + 12 负例 + 版本统一） | DONE |
| T7 | UAT V7（真实经 Import Center，20 检查，ids 6 新键） | DONE |
| T8 | 浏览器验收（5 角色 × 4 视口 × 8 页面） | DONE |
| T9 | Session P2 治理 | DONE |
| T10 | 全量回归 + 文档/handbook + FINAL-REPORT（53 项） | DONE |

诚实边界：机器 Gate 只能输出 READY_FOR_REAL_DATA_UAT 或具体
BLOCKED；真实数据 UAT 与人工验收由用户执行，此前不得写
ACCEPTED/COMPLETE/PRODUCTION_READY。

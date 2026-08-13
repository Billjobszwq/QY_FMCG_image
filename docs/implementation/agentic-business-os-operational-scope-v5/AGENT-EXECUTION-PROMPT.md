# AGENT-EXECUTION-PROMPT · Operational Scope V5

你正在执行《Agentic Business OS · Operational Scope V5》纠偏。
事实源：本目录全部文档 + `.eval/scope_v5/`。禁止相信旧报告；一切
以现场只读复现为准（00-LIVE-AUDIT.md）。

## 循环（不得分阶段停下询问）
现场审计 → 根因复现 → 红测试 → 架构契约 → 小步实现 → 单元/集成/
权限负例 → 浏览器验收 → 数据库对账 → Gate 自动重算 → 全量回归 →
文档/手册 → 最终报告（53 项）。

## 红线（摘要）
1. 改库前 SQLite Backup API 备份 + 双向 integrity（已执行，见 00）。
2. 不删历史数据；纠偏追加式/版本化；quarantine 代替删除。
3. 禁 git reset --hard / add -A / merge / push / deploy / 切
   production / 启动训练；不触碰受保护未跟踪资产。
4. 运行时作用域判断禁止依赖 uat/demo 文件名（仅历史诊断可用）。
5. 每个修复先红测试后实现，小步 commit（带 OSV5 编号）。
6. Gate 只能由 evaluate_gate_from_evidence 生成；不得手写 READY。

## 关键契约（详见 01–07）
- 批次 = 冻结的执行上下文（tenant/scope/test_run/actor/source/
  correlation + 多客户关联 + 授权决定 + 提交证据）。
- Import API 全端点接入 IAMService：模板权限矩阵 + 逐客户授权 +
  DTO 白名单 + preview 脱敏。
- Scope Registry = 可执行唯一事实源：类型化声明 + validator +
  scanner/archiver/filter/TestCenter/Gate 全部派生。
- 历史 20 条：只读 plan → 唯一归属绑定 / quarantine，幂等+审计。
- Gate 3.2.0：18 新检查 + ≥12 负例 + 全链路版本一致。
- UAT V7 必须真实经 multipart Import API；ids 含 6 个 import 键。

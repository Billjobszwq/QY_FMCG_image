# STATUS

## 总体

`DESIGN_APPROVED / READY_FOR_UAT`（G0–G9 fresh PASS；live hash 未变；
全量回归 2242 passed/0 failed；详见 ACCEPTANCE-REPORT。READY_FOR_UAT
不是上线、不是验收通过；ACCEPTED 需人工真实 UAT 明确确认。）

## 设计确认

| 项目 | 状态 |
|---|---|
| 模型管理为独立系统级一级模块 | APPROVED |
| 本地 OMLX + OpenAI/OpenAI-compatible + Anthropic | APPROVED |
| 模型连接、模型目录、能力分配分离 | APPROVED |
| 普通员工无入口、无配置 API 权限 | APPROVED |
| API Key 加密、不可回显 | APPROVED |
| maker/checker + CAS + Canary + 回滚 | APPROVED |
| 账号级 Token、监控、配额和成本 | APPROVED |
| 首个真实接入为本地 OMLX Embedding | APPROVED |

## 实施任务

| Task | 内容 | 状态 | Gate |
|---|---|---|---|
| M1 | 只读基线、资产保护和迁移预检 | DONE | G0 ✅（E-MM-1） |
| M2 | 数据契约、加密 SecretStore、EndpointPolicy | DONE | G1 ✅（E-MM-2） |
| M3 | OpenAI-compatible 与 Anthropic Adapter | DONE | G2 ✅（E-MM-3） |
| M4 | Connection/Catalog/Binding/Resolver 服务 | DONE | G3 ✅（E-MM-4） |
| M5 | IAM、导航投影与 maker/checker | DONE | G4 ✅（E-MM-5） |
| M6 | 账号级 Usage、Token、预算、限流与监控 | DONE | G5 ✅（E-MM-6） |
| M7 | OMLX Embedding、索引重建与语义 Gate | DONE | G6 ✅（E-MM-7） |
| M8 | Agent/模块绑定与兼容回退 | DONE | G7 ✅（E-MM-8） |
| M9 | 独立模型管理 UI 与浏览器验收 | DONE | G8 ✅（E-MM-9） |
| M10 | 全量验证、对账、Canary 与 UAT 准备 | DONE | G9 ✅（E-MM-10） |

## 允许的终态

- `IMPLEMENTATION_NOT_STARTED`
- `IN_PROGRESS`
- `BLOCKED_BY_SECRET_KEK`
- `BLOCKED_BY_PROVIDER_AUTH`
- `BLOCKED_BY_SEMANTIC_GATE`
- `READY_FOR_UAT`
- `ACCEPTED`

`READY_FOR_UAT` 只允许在 G0–G9 全绿后写入；`ACCEPTED` 只允许在人工真实 UAT 后写入。

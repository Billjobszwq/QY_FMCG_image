# Platform V2 — DECISIONS

> 格式：ID | 日期 | 决策 | 依据 | 状态

| ID | 日期 | 决策 | 依据 | 状态 |
|---|---|---|---|---|
| PV2-D-001 | 2026-08-01 | 平台代码目录采用手册 §7 边界：`src/platform/{api,kernel,modules,iam,data,assets,jobs,usage,audit,adapters/legacy}` + `src/modules/` + `web/src/{platform,modules}` + `contracts/`；src/platform 禁止 import src/modules | 手册 §7、L0 八条架构规则 | ACTIVE |
| PV2-D-002 | 2026-08-01 | M1–M3 持久化用单一 SQLite PlatformStore（新库，独立于 .warehouse），M6 一次性迁移 PostgreSQL，不双写 | 手册 §5.3 | ACTIVE |
| PV2-D-003 | 2026-08-01 | 旧 `.warehouse/db.sqlite` 默认只读访问（`mode=ro`），新平台不写旧库 | 手册 §5.3、数据保护红线 | ACTIVE |
| PV2-D-004 | 2026-08-01 | 8091/8092 以 legacy adapter（`legacy.recognition.v2` / `legacy.training.monitor`）注册为 Capability，第一阶段不重写不切换生产入口 | 用户指令、手册 §6 M1/M2 | ACTIVE |
| PV2-D-005 | 2026-08-01 | 健康语义三级：healthy / degraded / unavailable；任一非关键依赖 DOWN → 8400 整体 degraded 但持续服务 | 手册 §3.1、用户 degraded 要求 | ACTIVE |
| PV2-D-006 | 2026-08-01 | 原图进 CAS（内容寻址，复制哈希件），数据库只存 ResourceRef/哈希/lineage；原图目录只读不动 | L0 CAS 设计、手册 §8 | ACTIVE |
| PV2-D-007 | 2026-08-01 | 冻结三值：production_switch=false、training_started=false、deleted_files=false；训练启动与模型发布为两个独立审批动作 | 用户指令 | ACTIVE |
| PV2-D-008 | 2026-08-01 | Kernel 泛化验证以 `system_health_v1` 非识别 Graph 为准；Graph Runtime 内禁止 FMCG 特例代码 | L0 规则、手册 M3 | ACTIVE |

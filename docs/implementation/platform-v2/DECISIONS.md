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
| PV2-D-009 | 2026-08-05 | 执行入口切换为 `2026-08-05-unified-management-all-photo-training-execution-manual.md`（唯一实施手册）；旧 M0–M6 里程碑口径由审计纠偏接管，M5 保持 REOPENED 直至 G-TRUTH/G-EVAL/G-SNAPSHOT 有机器证据 | 用户指令、2026-08-05 独立审计 | ACTIVE |
| PV2-D-010 | 2026-08-05 | 工作分支切换为 `feat/unified-workbench-training-readiness`（基于 `9db9946`）；审计文档改动随本分支提交，不回写 `feat/usable-platform-foundation` | 手册 §10 Git 规范 | ACTIVE |
| PV2-D-011 | 2026-08-05 | U1 实施原则：recall@FP 改为全数据集统一置信度阈值扫描（逐阈值 conf 降序 one-to-one 配对），FP_total = duplicate + localization + background + taxonomy（守恒式）；旧逐图 TopK 口径与锁定测试一并作废改写 | 手册 §3.1 UMT-001/002 | ACTIVE |
| PV2-D-012 | 2026-08-05 | DatasetSnapshot 只能由服务端 builder 生成（逐文件存在/SHA/标签/data.yaml/五键守卫/近重复/冻结协议校验）；拒绝客户端自由 JSON 与自由文本审核结论；演示 Snapshot `072aeebe` 标记 demo/invalid_for_training，不物理删除 | 手册 §3.1 UMT-003/004、红线不删除 | ACTIVE |
| PV2-D-013 | 2026-08-05 | dry-run 命令必须落在 `train_v1.py` 真实 argparse 参数集内（--data-yaml/--run-name/--epochs/--imgsz 等；无 --dataset/--budget-minutes），并通过 CLI parse 预检（no-train）后才可入库 | 手册 §3.1 UMT-002 验收 | ACTIVE |
| PV2-D-014 | 2026-08-05 | MPS G0 必须实测（arm64/torch MPS built+available/矩阵/模型前向/无 CPU fallback/AC 电源/内存/swap/磁盘），证据写 training_run；`sys.platform=="darwin"` 判定作废 | 手册 §3.1 UMT-005、T0 | ACTIVE |
| PV2-D-015 | 2026-08-05 | 训练授权拆为两个动作：approve_plan（批准训练计划）与 enqueue_training_job（提交可恢复 Worker Job）；可信本机 login session/CSRF 取代客户端 X-Role/X-Actor 自证 | 手册 §3.1 UMT-006/007 | ACTIVE |
| PV2-D-016 | 2026-08-05 | 训练授权范围仅 T1（1ep smoke）→T2（3ep P0/P1 pilot），且需 UMT-001~008、G-EVAL、G-SNAPSHOT、G-ASSET、G-LABEL、G-MPS 全部有机器证据；T2 后立即停止报告；10ep/多 seed/classifier 重训/开封 gold/发布/PG 生产切换/删除制品均需新授权 | 用户指令、手册 §7 | ACTIVE |
| PV2-D-017 | 2026-08-05 | 照片总量只能以 source_asset_inventory_v1 的 SHA 唯一数表述；禁止目录数量相加；原图只读不动，全部 source reference 保留 | 手册 §5.1、U3 | ACTIVE |

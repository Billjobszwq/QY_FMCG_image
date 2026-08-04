# Platform V2 — PLAN（M0–M7 / W0–W11 可勾选清单）

> 来源：`2026-08-04-continuous-usable-framework-execution-manual.md` §6（里程碑）与 §13（工作包）。
> 勾选规则：只有"真实启动 + 测试通过 + 浏览器/CLI 证据 + EXECUTION-LOG 记录"后才能勾选。

## 里程碑 M0–M7

### M0 基线与保护
- [x] 从 c9998af 创建 `feat/usable-platform-foundation`
- [x] 建立 platform-v2 六份文档（STATUS/PLAN/EXECUTION-LOG/ISSUES/DECISIONS/ACCEPTANCE）
- [x] 只读盘点：git 状态、服务端口、170 测试、warehouse 计数、bundle verify、磁盘占用、未跟踪制品
- [x] 冻结 `production_switch=false`、`training_started=false`、`deleted_files=false`
- [x] M0 小提交 → f91c0e6

### M1 统一 Web Shell（http://127.0.0.1:8400）
- [x] 8400 FastAPI 启动，`/api/v1/health` 汇总 8091/8092/8300/8301/8455 状态
- [x] React+Vite Web Shell（web/），由 8400 提供
- [x] 系统总览页（服务状态、degraded 明确显示）
- [x] 图片识别页（上传入口，M1 阶段可先对接 8091）
- [x] 训练模型只读页（8092 数据）
- [x] 标注 degraded 页（8300 DOWN 时明确标记）
- [x] 8300/8301/8304 不可用时 8400 正常运行并显示 degraded
- [x] 浏览器 E2E 验证 + 8091/8092 不受影响证明

### M2 最小可信 Foundation
- [ ] IAM 最小模型（用户/角色/权限，本机单租户起步）
- [ ] Module Manifest + Capability Registry（模块注册，不直接 import）
- [ ] Asset / Evidence / Audit / Usage 契约冻结（Pydantic + fixture + 测试）
- [ ] Job/Attempt 状态机（可识别 orphaned，可恢复语义）
- [ ] RequestContext：request_id / run_id / idempotency_key / UTC 时间
- [ ] legacy adapters（8091/8092）注册为 Capability
- [ ] migration + PlatformStore 备份校验
- [ ] src/platform 不 import src/modules 的依赖方向测试

### M3 第一条真实 Graph
- [ ] GraphDefinition/GraphVersion 不可原地修改（版本化测试）
- [ ] GraphRun / NodeExecution / Checkpoint 持久化
- [ ] 状态机：running / waiting_human / failed / completed（+预算/超时/最大节点/循环上限）
- [ ] 重试不重复副作用（idempotency）
- [ ] `fmcg_photo_inspection_v1`：上传→CAS→质量→8091识别→人工门→EvidenceBundle→Usage/Audit→RecognitionResult
- [ ] `system_health_v1`：非识别 Graph，证明 Kernel 无 FMCG 硬编码
- [ ] Run UI：列表/详情/节点时间线/证据查看
- [ ] 浏览器 E2E 完整走一条真实照片流程
- [ ] M3 完成前全量测试重新验证

### M4 Label Studio 闭环（M3 后）
- [ ] Label Studio 原生 1.23.0 启动（修 start_label_studio.sh 路径问题）
- [ ] assisted / blind 项目分离
- [ ] webhook inbox 去重 + API 对账
- [ ] 先 10 张 E2E，再 50 张；不直接生成 2300 张

### M5 数据集训练治理（需授权）
- [ ] DatasetSnapshot 契约
- [ ] 修 truebox 评估：真实 FP/photo 预算扫描（当前为 TopK，不得用于晋级）
- [ ] E0/P0/P1 统一推理导出
- [ ] dry-run 能力；训练启动需显式人工授权；发布独立审批；禁 auto_switch

### M6 PostgreSQL + 可靠 Worker
- [ ] 单次迁移（不双写），CAS 备份恢复演练
- [ ] 可恢复 Worker（替代 daemon thread）
- [ ] 安全加固 + 性能测试

### M7 后续 Domain Pack
- [ ] （保留，不在第一阶段）

## 工作包 W0–W11

- [x] **W0 Baseline**：只读盘点 + 基线记录（见 EXECUTION-LOG #1–#6）
- [x] **W1 Scaffold**：`src/platform/` + `web/` 目录、依赖（锁定版本+许可证）、8400 启动命令、health 端点骨架
- [x] **W2 Health adapters**：8091/8092/8300/8301/8455 探测适配器；超时/失败类型/降级标记；`/api/v1/health` 汇总
- [x] **W3 Web Shell**：Vite+React+TS；7 页骨架（系统总览/Graph Runs/图片识别/标注审核/数据资产/训练模型/系统状态）；8400 静态托管
- [x] **W4 Recognition bridge**：`legacy.recognition.v2` adapter → 8091；上传→识别→结果展示
- [ ] **W5 PlatformStore**：SQLite 开发适配器（M1–M3 专用，M6 一次性迁移 PG）；Run/Node/Checkpoint/Job/Audit/Usage/Evidence 表
- [ ] **W6 Capability Registry**：ModuleManifest、注册函数、依赖方向守卫测试
- [ ] **W7 Graph Kernel**：GraphDefinition/Version、Run 状态机、Checkpoint、预算/超时/循环节制、幂等重试
- [ ] **W8 Asset/CAS**：内容寻址存储；数据库只存 ResourceRef/哈希/lineage；原图不动
- [ ] **W9 FMCG Graph**：fmcg_photo_inspection_v1 节点链 + 人工门（waiting_human）+ EvidenceBundle
- [ ] **W10 Run UI**：Graph Runs 列表/详情/节点时间线/证据浏览器
- [ ] **W11 M3 Acceptance**：全量测试 + 浏览器 E2E + system_health_v1 非识别验证 + 报告

## 技术基线约定

- Python 3.13 不降级；FastAPI + Pydantic；API 前缀 `/api/v1`
- 健康语义：healthy / degraded / unavailable
- M1–M3 单一 SQLite PlatformStore（不双写）；旧 `.warehouse/db.sqlite` 默认只读
- 端口：8400 主入口；8091/8092 内部 legacy；8300 LS 代理跳转；8455 内部
- 前端：TypeScript + React + Vite（web/）

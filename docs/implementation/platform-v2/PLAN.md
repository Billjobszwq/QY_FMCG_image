# Platform V2 — PLAN（历史 M0–M7 + 当前 U0–U5/T0–T2）

> 当前来源：`2026-08-05-unified-management-all-photo-training-execution-manual.md`。M0–M7 保留历史建设轨迹；2026-08-05 审计重新打开 M5。
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
- [x] IAM 最小模型（用户/角色/权限，本机单租户起步）
- [x] Module Manifest + Capability Registry（模块注册，不直接 import）
- [x] Asset / Evidence / Audit / Usage 契约冻结（Pydantic + fixture + 测试）
- [x] Job/Attempt 状态机（可识别 orphaned，可恢复语义）
- [x] RequestContext：request_id / run_id / idempotency_key / UTC 时间
- [x] legacy adapters（8091/8092）注册为 Capability
- [x] migration + PlatformStore 备份校验
- [x] src/platform 不 import src/modules 的依赖方向测试

### M3 第一条真实 Graph
- [x] GraphDefinition/GraphVersion 不可原地修改（版本化测试）
- [x] GraphRun / NodeExecution / Checkpoint 持久化
- [x] 状态机：running / waiting_human / failed / completed（+预算/超时/最大节点/循环上限）
- [x] 重试不重复副作用（idempotency）
- [x] `fmcg_photo_inspection_v1`：上传→CAS→质量→8091识别→人工门→EvidenceBundle→Usage/Audit→RecognitionResult
- [x] `system_health_v1`：非识别 Graph，证明 Kernel 无 FMCG 硬编码
- [x] Run UI：列表/详情/节点时间线/证据查看
- [x] 浏览器 E2E 完整走一条真实照片流程
- [x] M3 完成前全量测试重新验证

### M4 Label Studio 闭环（M3 后）
- [x] Label Studio 原生 1.23.0 启动（修 start_label_studio.sh 路径问题）
- [x] assisted / blind 项目分离
- [x] webhook inbox 去重 + API 对账
- [x] 先 10 张 E2E，再 50 张；不直接生成 2300 张
- [ ] 人工标注/双审/仲裁（需授权，暂停中）

### M5 数据集训练治理（REOPENED / NO-GO）
- [ ] DatasetSnapshot 真实契约（文件/标签/data.yaml/五键/近重复/冻结协议/审核/质量/builder audit/hash）
- [ ] 修 truebox 评估：全局阈值真实 FP/photo 扫描 + total FP 守恒；TopK 不得用于晋级
- [ ] E0/P0/P1 在同一人工 truebox 上统一推理与评估
- [ ] 合法 dry-run 命令 + 真实 MPS G0 + 可信批准 + 可恢复训练 Job + 独立发布审批
- [ ] 训练启动（需授权，暂停中；training_started=false）

### M6 PostgreSQL + 可靠 Worker
- [x] 单次迁移脚本（不双写，逐表计数+哈希核对）；真实演练通过（brew PG 16.14，16/16 match）；生产切换待独立授权
- [x] CAS 备份恢复演练（verify_all/backup/restore/磁盘水位）
- [x] 可恢复 Worker（lease 认领/崩溃恢复/取消/超时/重试/dead-letter/背压）
- [x] 安全加固（CORS 白名单/分享 token scope+有效期/审计）+ 性能测试（100 job 吞吐基线）

### M7 后续 Domain Pack
- [ ] （保留，不在第一阶段）

## 2026-08-05 当前执行清单

### U0 事实恢复
- [x] 当前分支/HEAD、310+1 测试、服务、开发库、页面和照片池只读复核
- [x] 新建统一管理与全量照片训练执行手册
- [x] STATUS/PLAN/ISSUES/ACCEPTANCE/EXECUTION-LOG 审计纠偏
- [ ] 实施 Agent 建立逐任务 LIST、owner、依赖、证据和 commit

### U1 训练真实性 P0
- [ ] UMT-001～UMT-008 全部 TDD 修复
- [ ] 独立参考 evaluator 和对抗样例一致
- [ ] 演示 Snapshot 不可训练；真实 builder Snapshot 通过
- [ ] 合法 CLI parse check、真实 MPS G0、可信身份和可恢复 Job 通过

### U2 统一管理 MVP
- [ ] 角色首页和统一任务中心
- [ ] 真实数据资产/CAS/lineage/quality 页面
- [ ] 识别文件/批量/URL/API/Agent 统一任务
- [ ] 标注审核、训练、Graph+Loop 和系统管理使用统一业务状态
- [ ] 普通用户浏览器 E2E，无需理解 M 编号/raw JSON

### U3 全照片资产与质量
- [ ] 全部来源进入 `source_asset_inventory_v1`
- [ ] SHA 精确去重 + pHash/embedding 近重复组
- [ ] 每个源照片有用途和冻结角色；数量守恒；原图不动
- [ ] qpol_v2 + 500～1,000 张人工质量金标准入口与混淆矩阵

### U4 SAM 与人工闭环
- [ ] 100 张 point→SAM→review→final box E2E
- [ ] 500→2,000→全 eligible 可恢复扩展与批次质量门
- [ ] 链接派发、认领、单审、10% 盲抽、异常双审/仲裁
- [ ] 250 条旧 pending 状态真实接入，不伪造

### U5 Graph+Loop v2
- [ ] typed edges / router / loop / convergence / per-loop budget
- [ ] sequential v1 兼容与旧 run 可回放
- [ ] 全照片准备训练 Loop 真实 E2E

### T0/T1/T2 Apple MPS pilot
- [ ] T0 真实 MPS G0 + 768/960/1024 batch benchmark
- [ ] T1 1 epoch smoke（所有前置门通过后授权）
- [ ] T2 3 epoch P0/P1 pilot（T1 全绿后授权）
- [ ] T2 后停止；未授权 10ep/发布/生产切换

## 工作包 W0–W11

- [x] **W0 Baseline**：只读盘点 + 基线记录（见 EXECUTION-LOG #1–#6）
- [x] **W1 Scaffold**：`src/platform/` + `web/` 目录、依赖（锁定版本+许可证）、8400 启动命令、health 端点骨架
- [x] **W2 Health adapters**：8091/8092/8300/8301/8455 探测适配器；超时/失败类型/降级标记；`/api/v1/health` 汇总
- [x] **W3 Web Shell**：Vite+React+TS；7 页骨架（系统总览/Graph Runs/图片识别/标注审核/数据资产/训练模型/系统状态）；8400 静态托管
- [x] **W4 Recognition bridge**：`legacy.recognition.v2` adapter → 8091；上传→识别→结果展示
- [x] **W5 PlatformStore**：SQLite 开发适配器（M1–M3 专用，M6 一次性迁移 PG）；Run/Node/Checkpoint/Job/Audit/Usage/Evidence 表
- [x] **W6 Capability Registry**：ModuleManifest、注册函数、依赖方向守卫测试
- [x] **W7 Graph Kernel**：GraphDefinition/Version、Run 状态机、Checkpoint、预算/超时/循环节制、幂等重试
- [x] **W8 Asset/CAS**：内容寻址存储；数据库只存 ResourceRef/哈希/lineage；原图不动
- [x] **W9 FMCG Graph**：fmcg_photo_inspection_v1 节点链 + 人工门（waiting_human）+ EvidenceBundle
- [x] **W10 Run UI**：Graph Runs 列表/详情/节点时间线/证据浏览器
- [x] **W11 M3 Acceptance**：全量测试 + 浏览器 E2E + system_health_v1 非识别验证 + 报告

## 技术基线约定

- Python 3.13 不降级；FastAPI + Pydantic；API 前缀 `/api/v1`
- 健康语义：healthy / degraded / unavailable
- M1–M3 单一 SQLite PlatformStore（不双写）；旧 `.warehouse/db.sqlite` 默认只读
- 端口：8400 主入口；8091/8092 内部 legacy；8300 LS 代理跳转；8455 内部
- 前端：TypeScript + React + Vite（web/）

# Platform V2 — IMPLEMENTATION-LIST（U0–U5 / T0–T2 逐任务清单）

> 手册：`docs/superpowers/plans/2026-08-05-unified-management-all-photo-training-execution-manual.md`（唯一实施入口）
> 分支：`feat/unified-workbench-training-readiness`（基于 `9db9946`）
> 规则：每项先红测试 → 最小实现 → 全量回归 → 浏览器/CLI 验证 → 独立小 commit；证据列写命令/截图/制品路径。

状态图例：TODO / RED（红测试已写）/ IMPL / DONE / BLOCKED

## U0 事实恢复与工作台账

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U0-1 | 建立/更新六治理文档（本文件+STATUS/ISSUES/DECISIONS/EXECUTION-LOG/PLAN） | — | agent | DONE | — | git status 保留未跟踪制品 | （随 U0 提交） | — |
| U0-2 | M5 标 REOPENED，演示 Snapshot 标不可训练（不物理删除） | U0-1 | agent | DONE | `tests/platform/test_u0_snapshot_marking.py`（3 红→绿） | 真实库 072aeebe trainable=0 + audit；gates registered_snapshots=0/can_train=false | c5fcca2 | — |
| U0-3 | 文档/代码/DB/UI 状态一致性自查（G-TRUTH） | U0-2 | agent | TODO | — | 逐项对照表 | — | — |

## U1 训练真实性 P0（UMT-001～008）

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U1-001 | recall@FP 改为全数据集统一置信度阈值扫描（one-to-one、FP 含重复/背景/定位、输出阈值与曲线）；独立参考实现 + 对抗测试 | — | agent | DONE | `tests/platform/test_umt001_true_fp.py`（5 红→绿） | "2 TP 后才出现第 1 个 FP"反例：FP1=2 TP；跨图统一阈值；随机 21 案例与内建参考实现互验 | 0908127 | 已改写旧锁定测试 |
| U1-002 | 错误账本互斥 + FP 守恒式 `FP_total = dup+loc+bg+taxonomy...`，门禁用 total FP/photo | U1-001 | agent | DONE | 守恒断言 + `test_promotion_gate_uses_total_fp_not_background_only` | `assert n_tp+total_fp==n_proposals` 内置 evaluate_truebox；门禁优先 total_fp | 0908127 | — |
| U1-003 | dry-run 生成 train_v1.py 真实支持的命令（--data-yaml/--run-name 等）+ CLI parse 预检（no-train 检查） | U1-002 | agent | DONE | `tests/platform/test_umt002_command.py`（5 红→绿） | 真实子进程 `--parse-check` 退出码 0；`--dataset` 被 allow_abbrev=False parser 拒绝；未知参数 fail-closed；默认 imgsz 960 非 1280 | 433f995 | data.yaml 路径默认 .datasets/<name>_<version>/，真实训练前需 builder 产出 |
| U1-004 | 演示 Snapshot 标 demo/invalid_for_training | U0-2 | agent | DONE | `tests/platform/test_u0_snapshot_marking.py` | migration 005（trainable/status_note 列）；幂等标记；dry_run 拒绝 demo | c5fcca2 | UI 展示待 U1-009 训练页分区 |
| U1-005 | 服务端 Snapshot builder：逐文件存在/SHA/标签/data.yaml/五键/近重复/协议/质量/审核校验；拒绝客户端自由 JSON | U1-004 | agent | DONE | `tests/platform/test_umt003_snapshot_builder.py`（8 红→绿）+ E2E 改写 | builder 逐文件校验 + SHA/pHash 去重 + 五键守卫 + protocol_guard + staging+data.yaml；POST /snapshots → 410，新增 POST /snapshots/build | 本批次提交 | 全量 332 passed + 1 skipped |
| U1-006 | MPS G0 真实门禁：arm64/torch MPS built+available/1024²矩阵/模型前向/无 fallback/电源/内存/swap/磁盘，证据写 run | U1-003 | agent | TODO | `tests/platform/test_umt005_mps_g0.py`（主机门控） | 任一失败禁用训练按钮 | — | 沙箱无 MPS，主机验证 |
| U1-007 | 可信身份：本机 login session/CSRF/服务端 role；禁止客户端 X-Role/X-Actor 自证 | U1-005 | agent | TODO | `tests/platform/test_umt006_auth.py` | 伪造 header 不能授权训练/批准门 | — | — |
| U1-008 | 拆分 approve_plan 与 enqueue_training_job；训练走 M6 可恢复 Worker（job/attempt/PID/log） | U1-007 | agent | TODO | `tests/platform/test_umt007_job_semantics.py` | 批准不消耗算力；启动产生 job | — | — |
| U1-009 | 训练页分区：演示/候选/可训练/活动 job/历史实验/生产模型；无活动 job 显 idle | U1-008 | agent | TODO | tsc+build+截图 | 浏览器 E2E | — | — |

## U2 统一管理 MVP

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U2-1 | 统一 WorkItem/Task API + 角色首页（我的待办/活动任务/阻断/下一步/负责人/异常） | U1 | agent | TODO | API 测试 + 截图 | 浏览器 E2E | — | — |
| U2-2 | 数据中心接真实 Asset/CAS/质量/血缘/审核/冻结；移除"CAS 未启用"假状态 | U3-台账可用 | agent | TODO | 截图 | 真实 CAS blob 数 | — | — |
| U2-3 | 识别统一：单文件/批量/URL/API/Agent 共用 RecognitionTask 服务层 | U2-1 | agent | TODO | API E2E | 四入口同任务历史 | — | — |
| U2-4 | 标注/审核/训练/识别/Graph Run 统一任务状态词汇；业务语言默认、技术字段折叠 | U2-1 | agent | TODO | 截图 | 普通用户 E2E | — | — |
| U2-5 | 写操作幂等键 + 分页筛选（UMT-109） | U2-1 | agent | TODO | 幂等测试 | 重复请求返回同任务 | — | — |

## U3 全部照片资产化

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U3-1 | 扫描 §5.1 全部来源（Excel/manifest/目录/URL/历史数据集） | U2-2 | agent | TODO | `tests/platform/test_u3_inventory.py` | 来源清单+原始数 | — | — |
| U3-2 | 不可变 source_asset_inventory_v1（追加式，原图不动） | U3-1 | agent | TODO | 不可变测试 | 数量守恒 | — | — |
| U3-3 | SHA 精确去重 + pHash/embedding 近重复组 | U3-2 | agent | TODO | 去重测试 | SHA 唯一数/近重复组数 | — | 22,664 张 batch3 哈希耗时需分段 |
| U3-4 | 用途与冻结角色分流（detector/classifier/包装版本/质量负样本/评估冻结/待标注/拒绝证据） | U3-3 | agent | TODO | 协议泄漏测试 | 每源照片有 disposition | — | — |
| U3-5 | qpol_v2 策略（斜拍/反光/翻拍/屏摄/摩尔纹/模糊/大头照/裁切/遮挡/场景/价签）+ 证据链 | U3-4 | agent | TODO | 策略测试 | 全字段证据 | — | — |
| U3-6 | 500–1,000 张分层人工质量金标准入口 + 混淆矩阵；人工未完成显示 waiting_human | U3-5 | agent+人 | TODO | — | waiting_human 截图 | — | 需真实人工 |

## U4 SAM 与人工闭环

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U4-1 | 点→SAM2.1 Hiera Small→候选→tight box，完整 lineage；疑难升级 Base+ | U3 | agent | TODO | SAM 契约测试 | 100 张 E2E | — | SAM 许可证/依赖隔离 |
| U4-2 | 链接派发/认领/单审/10% 盲抽/异常双审/仲裁/final box/不可变导出 | U4-1 | agent | TODO | 流程测试 | 状态机证据 | — | — |
| U4-3 | 250 条旧 diagnostic pending 真实接入（不伪造） | U4-2 | agent | TODO | 计数一致 | review_queue 250 → UI | — | — |
| U4-4 | 批次扩展 100→500→2,000→全 eligible，质量门不达标即停 | U4-3 | agent+人 | TODO | — | 每批质量报告 | — | 需真实人工 |

## U5 Graph+Loop v2

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U5-1 | NodeSpec/EdgeSpec/LoopSpec/RunState/HumanGate/GraphVersion 内核对象；sequential v1 兼容适配 | U1 | agent | TODO | kernel 测试 | typed edge/条件路由/收敛/预算 | — | — |
| U5-2 | 第一条真实 Loop：照片→质量→SAM/识别→人工→数据集→评估→误差回流 | U5-1 | agent | TODO | Loop E2E | 条件分支/人工暂停恢复/回流/预算停止各一次 | — | — |
| U5-3 | UI：轮次/决策原因/等待项/成本/证据/下一节点/停止原因 | U5-2 | agent | TODO | tsc+截图 | 浏览器 E2E | — | — |

## T0–T2 MPS 预检与受控训练（门控授权）

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| T0-1 | G0 主机证据：miniconda python、arm64、MPS built/available、矩阵+前向、无 fallback、AC+caffeinate、磁盘/内存/swap | U1-006 | agent | TODO | — | G0 证据文件 | — | — |
| T0-2 | 768/960/1024 三档 batch benchmark（images/s/峰值内存/swap/热状态），不默认 1280 | T0-1 | agent | TODO | — | benchmark 报告 | — | — |
| T0-3 | run 目录存在拒绝覆盖 + 服务 8091/8092/8400 训练期间健康 | T0-2 | agent | TODO | 防覆盖测试 | 健康快照 | — | — |
| T1 | 1 epoch smoke（全部 P0 门禁+G-EVAL/G-SNAPSHOT/G-ASSET/G-LABEL/G-MPS 机器证据通过后） | T0 | agent | BLOCKED | — | — | — | 门未过禁止 |
| T2 | 3 epoch P0/P1 pilot（T1 全绿后）；完成后立即停止报告，不发布 | T1 | agent | BLOCKED | — | — | — | 10ep/发布需新授权 |

## 冻结值（任何任务不得改变）

- production_switch=false、training_started=false、deleted_files=false
- 未跟踪制品 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不暂存不清理
- 不 `git add .`/`-A`；不 merge/push/deploy/force-push

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
| U0-3 | 文档/代码/DB/UI 状态一致性自查（G-TRUTH） | U0-2 | agent | DONE | 浏览器 E2E（登录流+训练页七分区+idle+console 无错误） | 逐项对照：文档 M5=REOPENED/DB trainable=0/代码 410+守卫/UI 演示分区标不可训练；截图 .eval/training_login_check_*.png | 87f16d5 | — |

## U1 训练真实性 P0（UMT-001～008）

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U1-001 | recall@FP 改为全数据集统一置信度阈值扫描（one-to-one、FP 含重复/背景/定位、输出阈值与曲线）；独立参考实现 + 对抗测试 | — | agent | DONE | `tests/platform/test_umt001_true_fp.py`（5 红→绿） | "2 TP 后才出现第 1 个 FP"反例：FP1=2 TP；跨图统一阈值；随机 21 案例与内建参考实现互验 | 0908127 | 已改写旧锁定测试 |
| U1-002 | 错误账本互斥 + FP 守恒式 `FP_total = dup+loc+bg+taxonomy...`，门禁用 total FP/photo | U1-001 | agent | DONE | 守恒断言 + `test_promotion_gate_uses_total_fp_not_background_only` | `assert n_tp+total_fp==n_proposals` 内置 evaluate_truebox；门禁优先 total_fp | 0908127 | — |
| U1-003 | dry-run 生成 train_v1.py 真实支持的命令（--data-yaml/--run-name 等）+ CLI parse 预检（no-train 检查） | U1-002 | agent | DONE | `tests/platform/test_umt002_command.py`（5 红→绿） | 真实子进程 `--parse-check` 退出码 0；`--dataset` 被 allow_abbrev=False parser 拒绝；未知参数 fail-closed；默认 imgsz 960 非 1280 | 433f995 | data.yaml 路径默认 .datasets/<name>_<version>/，真实训练前需 builder 产出 |
| U1-004 | 演示 Snapshot 标 demo/invalid_for_training | U0-2 | agent | DONE | `tests/platform/test_u0_snapshot_marking.py` | migration 005（trainable/status_note 列）；幂等标记；dry_run 拒绝 demo | c5fcca2 | UI 展示待 U1-009 训练页分区 |
| U1-005 | 服务端 Snapshot builder：逐文件存在/SHA/标签/data.yaml/五键/近重复/协议/质量/审核校验；拒绝客户端自由 JSON | U1-004 | agent | DONE | `tests/platform/test_umt003_snapshot_builder.py`（8 红→绿）+ E2E 改写 | builder 逐文件校验 + SHA/pHash 去重 + 五键守卫 + protocol_guard + staging+data.yaml；POST /snapshots → 410，新增 POST /snapshots/build | 50e39ff | 全量 332 passed + 1 skipped |
| U1-006 | MPS G0 真实门禁：arm64/torch MPS built+available/1024²矩阵/模型前向/无 fallback/电源/内存/swap/磁盘，证据写 run | U1-003 | agent | DONE | `tests/platform/test_umt005_mps_g0.py`（7 项含主机门控） | `mps_gate.run_mps_g0` 全项实测；dry_run 写入 mps_g0_report；start_training 对 G0 失败 fail-closed；主机 AC+MPS 实测全绿 | 7cd3c81 | 全量 339 passed + 1 skipped |
| U1-007 | 可信身份：本机 login session/CSRF/服务端 role；禁止客户端 X-Role/X-Actor 自证 | U1-005 | agent | DONE | `tests/platform/test_umt006_auth.py`（6 红→绿） | `src/platform/auth.py`（pbkdf2 口令/session 表 migration 006/CSRF 绑定）；training+jobs+share 写端点 require_principal；伪造 header → 401；DryRunBody imgsz 默认 1280→960 | 4085023 | 前端登录 UI 待 U1-009/U2；全量 345 passed + 1 skipped |
| U1-008 | 拆分 approve_plan 与 enqueue_training_job；训练走 M6 可恢复 Worker（job/attempt/PID/log） | U1-007 | agent | DONE | `tests/platform/test_umt007_job_semantics.py`（5 红→绿） | approve_plan 只落状态不提交 job；enqueue 需 approved+授权+G0，经 Worker training.run handler 真实子进程留 PID/日志；migration 007 job_id；新 API /approve-plan /enqueue | 5c13177 | 全量 350 passed + 1 skipped |
| U1-009 | 训练页分区：演示/候选/可训练/活动 job/历史实验/生产模型；无活动 job 显 idle | U1-008 | agent | DONE | tsc --noEmit + vite build（42 modules）+ 浏览器 E2E | Training.tsx 七分区（演示快照标不可训练/可训练/计划/已批准/活动 Job 显 idle/历史/生产）；App.tsx topbar 登录表单；api.ts CSRF 恢复（/auth/me 返回 csrf_token）；截图 .eval/training_login_check_*.png；全量 351 passed + 1 skipped | 87f16d5 | — |

## U2 统一管理 MVP

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U2-1 | 统一 WorkItem/Task API + 角色首页（我的待办/活动任务/阻断/下一步/负责人/异常） | U1 | agent | DONE | `tests/platform/test_u2_workitems.py`（5 红→绿）+ tsc/build | workitems.py 聚合真实来源（.review_queue 250 pending/训练 run/Job/标注批次）；Overview 改角色首页；真实库 254 待办/阻断横幅；截图 .eval/workbench_home_*.png；全量 356 passed | 516042b | 任务列表分页待 U2-5 |
| U2-2 | 数据中心接真实 Asset/CAS/质量/血缘/审核/冻结；移除"CAS 未启用"假状态 | U3-台账可用 | agent | DONE | `tests/platform/test_u2_assets.py`（4 项） | `/api/v1/assets/summary`+`/api/v1/assets`（真实台账+SHA 去重+用途分流）；页面卡片 38284/30459/6560/4684/1239 真实数字；筛选 photo1106=213 待标注；分页/折叠/console 无错 | 截图 `.eval/u22_assets_overview.png`/`.eval/u22_assets_filter_photo1106.png` | e2c32b2 |
| U2-3 | 识别统一：单文件/批量/URL/API/Agent 共用 RecognitionTask 服务层 | U2-1 | agent | DONE | `tests/platform/test_u2_recognition_tasks.py`（6 红→绿）+ tsc | migration 008 recognition_task；run_recognition_batch 四入口共享服务层（upload/url/API/Agent，身份来自服务端 session）；Recognition.tsx 四分区；真实照片批量识别 E2E 截图 .eval/recognition_unified_batch_verify.png；全量 362 passed | fc4ddfe | — |
| U2-4 | 标注/审核/训练/识别/Graph Run 统一任务状态词汇；业务语言默认、技术字段折叠 | U2-1 | agent | DONE | `tests/platform/test_u2_vocabulary.py`（3 红→绿）+ tsc/build | 新增 `src/platform/vocabulary.py`（UNIFIED_STATUS 11 词 + status_text 五类映射，未知状态 fail-closed 回显）；workitems 每条增 status_text/stage，任务标题去英文状态；Overview 状态列中文 + 高级详情 details 折叠（raw_status/photo_id/run_id 只进折叠区）；Recognition/Training 状态 pill 与筛选选项中文；浏览器 E2E：工作台 50/50 中文、高级详情默认折叠、识别/训练页中文、console 无错，截图 .eval/u24_business_language_*.png；全量 372 passed | 3710c0a | index.html 缓存可考虑 no-cache（非阻断） |
| U2-5 | 写操作幂等键 + 分页筛选（UMT-109） | U2-1 | agent | DONE | `tests/platform/test_u2_idempotency_paging.py`（7 红→绿）+ tsc/build | migration 009（recognition_task.idempotency_key + 唯一索引）；upload/url 读 Idempotency-Key 重复返回同一任务；任务列表 limit/offset/status + 全量 count；workitems limit/offset/kind/status；重复 enqueue 返回同一 Job；前端随机 UUID 幂等键 + 历史筛选分页；浏览器 E2E 截图 .eval/u25_recognition_paging_verify.png（请求头含 Idempotency-Key，真实照片批量识别成功）；全量 369 passed | f0e87c1 | — |

## U3 全部照片资产化

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U3-1 | 扫描 §5.1 全部来源（Excel/manifest/目录/URL/历史数据集） | U2-2 | agent | DONE | `tests/platform/test_u3_inventory.py`（6 项） | 来源清单+原始数：total_raw=38284（含重复，非唯一数）；batch1=2947/batch2=6510/batch3_clean=22659 精确复现 | `.eval/u3/source_scan_v1.json`（gitignore 本地证据） | 4384b71 |
| U3-2 | 不可变 source_asset_inventory_v1（追加式，原图不动） | U3-1 | agent | DONE | `tests/platform/test_u3_ledger.py`（6 项：幂等/同 SHA 多来源保留/触发器禁 DELETE+UPDATE/筛选分页/守恒） | migration 010（表+BEFORE DELETE/UPDATE 触发器）；真实库建账 38284 条 == total_raw 守恒，38284 条全带 SHA，重跑幂等 0 新增，6.5s | `.eval/u3/ledger_build_v1.json` | 8899d25 |
| U3-3 | SHA 精确去重 + pHash/embedding 近重复组 | U3-2 | agent | DONE | `tests/platform/test_u3_dedup.py`（5 项：唯一数/重复组保留全部 source ref/pHash 亮度扰动同组/唯一文件扫描/报告字段） | 真实库：38284 引用→**SHA 唯一 30459**，精确重复组 6560，pHash 近重复组 52（1288 本地文件，自实现 DCT-pHash 汉明≤ 8，无新增依赖），下载失败 0，耗时 89s | `.eval/u3/dedup_report_v1.json` | e44c9e1 |
| U3-4 | 用途与冻结角色分流（detector/classifier/包装版本/质量负样本/评估冻结/待标注/拒绝证据） | U3-3 | agent | DONE | `tests/platform/test_u3_disposition.py`（7 项含协议泄漏测试） | 7 用途规则引擎；真实库 38284 行全部有用途（0 空档），frozen→training 泄漏 0；分布：detector 候选 32116/classifier 32356/包装版本 427/质量负 5/评估冻结 4684/待标注 1239/拒绝证据 5 | `.eval/u3/disposition_report_v1.json` | 8f40ea5 |
| U3-5 | qpol_v2 策略（斜拍/反光/翻拍/屏摄/摩尔纹/模糊/大头照/裁切/遮挡/场景/价签）+ 证据链 | U3-4 | agent | DONE | `tests/platform/test_u3_qpol_v2.py`（7 项：11 维/全字段/不可变/waiting_human fail-closed/模糊与反光对抗测试） | migration 011 quality_decision_v1（触发器不可变，SHA/策略版本/分数/阈值/自动结论/人工结论/模型版本/证据全字段）；`src/platform/quality/qpol_v2.py` 11 维，blur/reflection 启发式（heuristic_v1），其余 9 维 waiting_human 禁止伪造；真实照片冒烟 10 张：5 fail/5 waiting_human、0 pass | — | bc97de6 | 9 维待人工金标准后训练分析器（U3-6/U4） |
| U3-6 | 500–1,000 张分层人工质量金标准入口 + 混淆矩阵；人工未完成显示 waiting_human | U3-5 | agent+人 | DONE（入口+状态机+首批 500；人工审核进行中） | `tests/platform/test_u3_gold.py`（6 项）+`tests/platform/test_u3_gold_api.py`（5 项：未登录 401/伪造头拒绝/reviewer 取 session/非法 verdict 422） | migration 012 quality_gold_v1+quality_human_v1（触发器不可变，同 SHA 仅一次）；`src/platform/quality/gold.py` 分层轮转建队/状态推导/混淆矩阵；真实库建队 **500**（fail 层 5+无结论层 495，幂等重跑 0，waiting_human 500→审核中）；浏览器 E2E 全绿（未登录待审核/登录提交后 499/1/不可改） | `.eval/u36_gold_before_login.png`、`.eval/u36_gold_after_verdict.png` | 98fa4cc | 剩余 499 张需真实人工逐张审核 |

## U4 SAM 与人工闭环

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U4-1 | 点→SAM2.1 Hiera Small→候选→tight box，完整 lineage；疑难升级 Base+ | U3 | agent | DONE | `tests/platform/test_u4_sam_lineage.py`（4 项：全链路字段/无疑难不调 Base+/manual_required 无假框/不可变） | migration 013 sam_lineage_v1（point→prompt→mask→box 全字段，触发器不可变）；`src/platform/annotate/sam_pipeline.py` 复用 sam_assist（prompts/硬约束筛选/rules_v1），隔离 .venv_sam worker；真实 MPS 冒烟 2 照 8 点：2 accepted（Small 直出 tight box）/6 manual_required（升级 Base+ 仍无合格候选，拒绝原因 multi_component×8 等，无假框） | `.eval/u4/smoke_report_20260805_130608.json`（gitignore 本地） | 7cffebf | 真实照片疑难率高（货架拥挤），人工闭环（U4-2）承接 |
| U4-2 | 链接派发/认领/单审/10% 盲抽/异常双审/仲裁/final box/不可变导出 | U4-1 | agent | DONE | `tests/platform/test_u4_review_flow.py`（11 项）+ `tests/platform/test_u4_review_api.py`（5 项） | migration 014：`review_task_v1`（任务不可变）+`review_event_v1`（追加式事件，状态全由事件推导）；`src/platform/annotate/review.py` 状态机；`src/platform/api/review.py` session+CSRF 仲裁仅 admin；浏览器 E2E 250 pending 认领后 249/1 console 无错 | `.eval/u4/u42_review_ui_250pending.png`、`.eval/u4/u42_review_ui_claimed.png` | cc190a8 | 真实人工审核未开始 |
| U4-3 | 250 条旧 diagnostic pending 真实接入（不伪造） | U4-2 | agent | DONE | 真实队列幂等导入测试（250→0 重跑）+ 同照片双模式别名测试 | `scripts/import_u4_review_queue.py`：`.review_queue/review_queue_diag_v1.json` 250 条（200 double_review+50 blind_manual，幂等键含 review_mode）→ 生产库 review_task_v1，导入前备份 `.eval/u4/platform_backup_before_u43.sqlite`；UI 250 全部 pending | `.eval/u4/platform_backup_before_u43.sqlite`（gitignore 本地） | 3e1e4a0 | 队列仍全部 pending，需真实人工推进 |
| U4-4 | 批次扩展 100→500→2,000→全 eligible，质量门不达标即停 | U4-3 | agent+人 | PARTIAL | `tests/platform/test_u4_batches.py`（4 项：未完成 waiting_human/一致率 0.5 gate_failed 拒扩展/通过→阶梯 100/幂等重入+500） | `src/platform/annotate/batches.py`：BATCH_LADDER(100,500,2000,-1)、批次标签用 protocol 列、门=完成度+双审一致率≥0.8；status API 返回 batch_plan；UI 显示批次进度；真实库诊断批 0/250 诚实 waiting_human | `.eval/u4/`（curl/脚本输出） | 6baa389 | 机制 DONE；实际分批推进需真实人工完成 250 诊断批 |

## U5 Graph+Loop v2

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| U5-1 | NodeSpec/EdgeSpec/LoopSpec/RunState/HumanGate/GraphVersion 内核对象；sequential v1 兼容适配 | U1 | agent | DONE | kernel 测试 6/6 | typed edge/条件路由/收敛/预算 | tests/platform/test_u5_loop_kernel.py + src/platform/kernel/loop.py | ef1b4e1 |
| U5-2 | 第一条真实 Loop：照片→质量→SAM/识别→人工→数据集→评估→误差回流 | U5-1 | agent | DONE | Loop E2E 4/4 | 条件分支/人工暂停恢复/回流/预算停止各一次 | src/platform/loops/pipeline_v2.py + scripts/run_u5_real_loop.py + .eval/u5/ | b32fd2c | 生产库 run 历史保留 |
| U5-3 | UI：轮次/决策原因/等待项/成本/证据/下一节点/停止原因 | U5-2 | agent | DONE | tsc+浏览器 E2E | 浏览器 E2E：UI 批准人工门→run 完成，console 无错 | web/src/pages/GraphRuns.tsx + src/platform/api/loops.py + .eval/u5/u53_browser_evidence.json | 53e4b4b | — |

## T0–T2 MPS 预检与受控训练（门控授权）

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| T0-1 | G0 主机证据：miniconda python、arm64、MPS built/available、矩阵+前向、无 fallback、AC+caffeinate、磁盘/内存/swap | U1-006 | agent | DONE | test_umt005 11/11 | G0 ok=true 两跑：.eval/t0/t0_preflight_evidence_20260805_150704.json、..._151618.json | d58d554 | — |
| T0-2 | 768/960/1024 三档 batch benchmark（images/s/峰值内存/swap/热状态），不默认 1280 | T0-1 | agent | DONE | test_t0_preflight 13/13 | 两跑均选 768（8.19 img/s，peak 0.306 GB）；thermal 无 warning；swap 10867MB>8192 停止线如实报告 | d58d554 | swap 超限训练启动前须处置 |
| T0-3 | run 目录存在拒绝覆盖 + 服务 8091/8092/8400 训练期间健康 | T0-2 | agent | DONE | test_run_overwrite_guard | 健康快照：8091 /v2/health、8092 /api/live、8400 /api/v1/health 前后均 200（证据内 services_before/after） | d58d554 | — |
| T1 | 1 epoch smoke（全部 P0 门禁+G-EVAL/G-SNAPSHOT/G-ASSET/G-LABEL/G-MPS 机器证据通过后） | T0 | agent | BLOCKED | — | — | — | 门未过禁止 |
| T2 | 3 epoch P0/P1 pilot（T1 全绿后）；完成后立即停止报告，不发布 | T1 | agent | BLOCKED | — | — | — | 10ep/发布需新授权 |

## VLM Qwen3-VL 4B + Graph+Loop 级联专项（Task 0–18）

> 依据：`docs/superpowers/specs/2026-08-06-qwen3-vl-4b-graph-loop-cascade-design.md`（架构规格）+ `docs/superpowers/plans/2026-08-06-qwen3-vl-4b-graph-loop-cascade-implementation-plan.md`（唯一实施计划）
> 红线：当前 sku_v7_sam 训练（PID 90423）运行期间，所有真实 Qwen/MLX 重任务被 G-CURRENT/G-APPLE 门禁 fail-closed 阻断（BLOCKED_BY_ACTIVE_TRAINING）；不得下载权重、不得安装大依赖、不得真实前向。

| ID | 目标 | 依赖 | Owner | 状态 | 测试 | 证据 | Commit | 剩余风险 |
|---|---|---|---|---|---|---|---|---|
| VLM-000 | 运行事实对账：训练 PID/epoch/指标解析、治理偏差登记、STATUS 如实化 | — | agent | DONE | — | results.csv 解析（只读）、ISSUES 登记 | f29cbc7 | 训练未结束不做最终评估文档 |
| VLM-001 | 冻结级联契约 contracts.py（PredictionEnvelope/RegionRef/CandidateSet/RiskDecision/CascadePolicy/QwenSkuDecision） | VLM-000 | agent | DONE | `tests/platform/test_vlm_contracts.py`（13 红→绿） | extra=forbid+frozen；accepted 需 sku_id+evidence；NaN/Inf fail-closed；闭集守卫 | 6fe2a76 | 全量 518 passed |
| VLM-002 | Capability Registry 扩展（resource_class/residency/meter_units）+ FMCG manifest 8 能力 + 组合根注入 | VLM-001 | agent | DONE | `tests/platform/test_vlm_registry.py`（12 红→绿） | 8 能力 ID 冻结；qwen=cold/mlx_vlm/token 计量；旧 manifest 默认值兼容；守卫测试不 import 领域包 | bfd54f7 | 全量 530 passed |
| VLM-003 | ModelResidencyManager（hot/warm/cold、租约、TTL 卸载、熔断、审计） | VLM-002 | agent | DONE | `tests/platform/test_model_residency.py`（17 红→绿） | migration 015 追加式；状态 cold/loading/hot/unloading/failed；过期租约显式 reap（未 reap 仍占名额）；加载失败→failed 熔断；全操作写 audit；recover 恢复 loading；qwen max_concurrency=1 | 69fee0b | 全量 547 passed |
| VLM-004 | CascadePolicy 四档位（fast/standard/deep/expert）+ 策略入 checkpoint | VLM-001 | agent | DONE | `tests/platform/test_cascade_policy.py`（11 红→绿） | fast=S1/standard=S2/deep=S3/expert=S4；require_quality_gate 恒 True；vlm_concurrency=1；SLA 12/48h 为队列业务 SLA；policy_snapshot 可 JSON 化入 checkpoint；预算耗尽/未知商品必须转人工；未知档位 fail-closed | 80f0937 | 全量 558 passed |
| VLM-005 | risk.py 校准路由（calibrated_risk、硬冲突强制 S4、NaN fail-closed） | VLM-001 | agent | DONE | `tests/unit/test_cascade_risk.py`（14 红→绿） | 无校准器 CalibrationUnavailable；硬冲突强制升级 S4（超档/已在 S4→人工）；NaN/Inf/缺 top1→human；未知 stage 受控错误；校准器冻结 JSON+SHA256 验证；bootstrap_rule_v1 明确标注非概率校准；升级受档位 max_stage 约束 | d5b6d30 | 全量 572 passed |
| VLM-006 | 适配器：quality/scene/legacy_cascade(detect_regions+classify_region)/sam_refiner/sku_retrieval | VLM-002 | agent | DONE | `tests/unit/test_cascade_adapters.py`（15 红→绿）+ 旧 gate/SAM 回归 | detector 只出 region 不出 final SKU；classify 出 Top-K/margin/entropy/模型版本；SAM 三种 crop 引用，mask 失败保留原框+needs_review 不伪造；retrieval 闭集过滤；quality 四级词汇 fail-closed manual_review；scene 无证据诚实 unknown；recognize() 行为不变（src/pipeline/recognize.py 本轮无需改动） | 18391c9 | 全量 587 passed |
| VLM-007 | qwen3vl_mlx HTTP adapter（闭集外 needs_review、租约、mock backend） | VLM-003 | agent | DONE | `tests/unit/test_qwen3vl_adapter.py`（15 红→绿） | 受控 base_url（仅 http/https）；固定 prompt 模板忽略注入键；输出经 QwenSkuDecision 校验；闭集外 accepted→needs_review+sku_outside_candidate_set；非法 JSON/空响应→needs_review；registry_version 缺失 fail-closed 不发请求；429/503/超时可重试、其他 4xx 不重试；调用前 acquire 租约 finally release（busy 拒绝不发请求）；全 fake HTTP，不加载权重 | 9be0965 | 全量 602 passed |
| VLM-008 | VLM 数据链路：quality_gate tilt 修正（缺水平线→manual_review）+ split_guard 6 维 + builder + HF messages | VLM-001 | agent | DONE | `tests/platform/test_quality_gate.py`（+7）+ `tests/unit/test_vlm_split_guard.py`（12）+ `tests/unit/test_vlm_dataset_builder.py`（13）红→绿 | V2 处置：tilt 不可观测→manual_review+tilt_unobservable；单一弱启发式→warn 不自动 reject；≥2 维 fail 才 reject；旧 934 张 tilt reject 历史不改写，screen 脚本改 V2 处置新写证据；split_guard 六维跨 split 重叠 + frozen/active protocol 禁入 train；builder immutable staging+原子发布+目录已存在拒绝，manual_pending/reject/frozen/model_provisional 与 sam_geometry_verified 无裁决不进 train；每条 sample 含 SHA/宽高/box_px/bbox_1000/registry/label_source/weight/evidence；HF 行仅 images+messages 无手工 vision token；泄漏在发布前阻断且不留 staging | fe3de05 | 全量 634 passed |
| VLM-009 | Apple/MLX preflight 硬门禁（G-CURRENT/G-APPLE，训练冲突 fail-closed） | VLM-003 | agent | DONE | `tests/unit/test_vlm_preflight.py`（11 红→绿） | 12 项探针维度冻结（arm64/Apple Silicon/Metal/模型/processor/有限前向/AC/磁盘/内存/swap/热/服务健康）；进程表 train_v1/mlx_vlm.lora 或活跃租约→active_training_conflict；未授权下载→download_authorization_required；探针缺失抛 PreflightError、崩溃 fail-closed；输出目录已存在→output_dir_exists；CLI 证据写 .eval/vlm_preflight/<run_id>/ 不覆盖，mlx 未安装时诚实 fail-closed；pyproject 增 vlm-train 可选依赖声明（不随主环境安装）；本轮未执行真实 preflight（需下载授权） | 1eb8e19 | 全量 645 passed |
| VLM-010 | evaluate.py（coverage=0→precision None+gate 不过）+ benchmark.py（batch 1/2/4） | VLM-009 | agent | DONE | `tests/unit/test_vlm_evaluate.py`（17 项，模块不存在时为 RED） | 报告冻结：coverage/accepted_precision/Top1/Top5/unknown 与 new_package P-R/schema 合规/candidate escape/属性准确率/p50、p95/tokens/s/逐实例错误账本；零 coverage→accepted_precision=None+gate_pass=False；escape>0 或 schema 不合规阻断 gate；分母 0 一律 None；benchmark 矩阵 batch 1/2/4×两档视觉 token×QLoRA/BF16，每 probe 独立目录防覆盖，实测字段缺失 fail-closed，estimation_basis=measured（禁用照片数估时）；zero-shot/benchmark CLI 无 ok=true preflight 报告拒绝执行，本轮未真实运行 | acf0da3 | 全量 662 passed |
| VLM-011 | 受治理 QLoRA launcher（MLX-VLM 真实参数、禁 --use-mps/--num-epochs、completed_candidate 不发布） | VLM-010 | agent | DONE | `tests/platform/test_vlm_training_gov.py`（21 项，先红后绿） | 新建 `src/training/vlm/train.py`：证据链门禁（snapshot/preflight/zero-shot/benchmark 缺失、输出目录占用、训练冲突、未授权、batch 超 benchmark、epochs/rank/alpha/instance 超第一轮上限、train_vision 未独立授权）fail-closed 不短路；只生成 MLX-VLM 白名单参数（--model-path/--dataset/--batch-size/--epochs/--learning-rate/--grad-checkpoint/--gradient-accumulation-steps/--train-on-completions/--lora-rank/--lora-alpha/--output-path），禁 --use-mps/--num-epochs；业务名 qwen3-vl:4b、基础模型 mlx-community/Qwen3-VL-4B-Instruct-4bit 固定；`training_gov/service.py` 增 plan_vlm_training（kind=dry_run+status=vlm_dry_run，不改 schema 枚举）、complete_vlm_training（八件制品缺一拒绝，仅产生 completed_candidate，发布仍需独立 admin 审批）、set_vlm_vision_authorized（独立授权动作）；API 增 POST /api/v1/training/runs/vlm/plan（未登录拒绝、未授权 403、证据缺失 400）；`scripts/run_qwen3vl_lora.py` 无 ok=true preflight 拒绝，主环境诚实 blocked 不加载权重；真实 QLoRA 未执行（BLOCKED_BY_ACTIVE_TRAINING） | fa26d69 | 全量 683 passed |
| VLM-012 | cascade graph 14 节点 + 四条路由测试 + 预算/不可用/SLA/retry 语义 | VLM-004~007 | agent | DONE | `tests/platform/test_cascade_loop.py`（12 项，先红后绿） | 新建 `cascade/graph.py`：GraphV2 14 节点（quality/scene/detect/classify_fast/risk_s1/segment/reclassify/risk_s2/retrieve/risk_s3/vlm_rerank/risk_s4/human_review/finalize）+ typed edges，多条件节点全部 router 标签，未匹配 edge 内核 fail-closed，无 feedback 边；`cascade/service.py`：CascadeService 复用 LoopEngine（唯一 Orchestrator），策略快照随 run 冻结；四条路由：fast→S1 accepted、standard 升级 S2、expert 冲突→S4 Qwen 闭集裁决、unknown→S5 waiting_human 跨进程恢复；预算耗尽/VLM 不可用/SLA 过期一律转人工不静默接受；raw confidence 不路由（仅 decide_risk 校准）；billing 按 (node,round) 幂等，idempotency_key 重提不重复计费；轨迹含 policy/risk/budget before-after/SLA/模型/证据 ID；`adapters/human_review.py` S5 交接单（accepted 需 sku+证据）；回归 test_u5_loop_kernel/test_u5_real_loop 全绿，全 fake backend 不加载真实模型 | 1e9937b | 全量 695 passed |
| VLM-013 | billing.py + Job attempt_timeout_at/queue_deadline_at（追加式迁移、幂等计费） | VLM-012 | agent | DONE | `tests/platform/test_cascade_billing.py`（10 项，先红后绿） | 追加式迁移 016（只增不删）：job 表重建扩展 status CHECK 新增 expired 并增 attempt_timeout_at/queue_deadline_at 双时间戳（旧数据 COALESCE 回填），新建 cascade_usage 账本表 UNIQUE(run_id,billing_key)+索引，usage_event/graph_run/audit_event 等历史表全部保留不 drop/rename；`jobs.py`：expired 终态入状态机（running→expired），attempt_expired 与 queue_deadline_passed 语义分离（单次 VLM attempt 超时≠任务过期），expire_job_at_deadline 到期置 expired+写审计 job.queue_deadline_expired，已终态/未到期/无 deadline 一律 no-op 不覆盖结果；新建 `cascade/billing.py`：RATE_CARD_VERSION=rate-card.v1 七能力积分价目+tier 乘数（fast/standard 1.0、deep 1.2、expert 1.5），bill_attempt 全字段留痕（capability/model/model_version/photos/regions/tokens/compute_ms/tier/cold_start/cache_hit/rate_card_version/resource_cost/billed_cost），run 不存在 fail-closed 拒绝记账，相同 billing_key 重试返回首次账目不重复计费；create_job 支持双时间戳；回归 test_m6_worker/test_platform_store 全绿；12/48h 是队列业务 SLA 非单次推理 timeout | 57eb162 | 全量 705 passed |
| VLM-014 | cascade API 7 端点（shadow 默认、旧 8091 不变） | VLM-012 | agent | DONE | `tests/platform/test_cascade_api.py`（16 项，先红后绿） | 新建 `src/platform/api/cascade.py`：POST/GET /api/v1/cascade/tasks、详情/regions/trail/cancel、GET /api/v1/models/runtime 共 7 端点；请求体 pydantic extra=forbid，file_path/model/prompt/graph 等任意额外字段 422；tier/source 白名单校验（非法 400）；URL 入口 SSRF 防护（仅 http/https，localhost/私网/链路本地/保留地址拒绝）；未登录全端点 401，写端点 session+CSRF（伪造 X-Actor/X-Role 无效）；Idempotency-Key 重放返回同一 RecognitionTask 不重复执行级联；单文件/批量/URL/api/agent 五入口共用 recognition_task 台账（entry=cascade_<source>）；取消写审计 cascade.task_cancelled + run 置 cancelled（run 缺失容错）；提交响应 production_switch=false shadow 默认；旧 /api/v1/recognition/recognize 与 8091 口径不变且不触发新级联；app.py 增 cascade_router 参数 + bundle.cascade_service 自动装配；bundle.py PlatformBundle 增 cascade_service/model_residency 可选注入位；全 fake backend 零真实模型 | 见 commit | 全量 721 passed |
| VLM-015 | packaging.py 新包装状态机（Qwen 只建 candidate、supersede 追加） | VLM-012 | agent | PENDING | packaging 测试 | — | — | — |
| VLM-016 | Web 三页面（CascadeTasks/ModelRuntime/NewPackaging）+ tsc/build/浏览器 | VLM-014 | agent | PENDING | npm test + build + E2E | — | — | — |
| VLM-017 | shadow 评估 E0/E1/C1/C2（无真值报 not_evaluable，不造 pass） | VLM-014 | agent | PENDING | shadow 测试 | — | — | 真实 shadow 被门禁阻断 |
| VLM-018 | runbook + 状态语义对齐 + 最终回归 + git 审计 | 全部 | agent | PENDING | 全量回归 | — | — | production bundle 不切换 |

## 冻结值（任何任务不得改变）

- production_switch=false、training_started=false、deleted_files=false
- 未跟踪制品 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 不暂存不清理；另 `.models/ .datasets/ .eval/` 不得暂存
- 不 `git add .`/`-A`；不 merge/push/deploy/force-push
- sku_v7_sam 训练运行期间：不 kill/暂停/改参数；不启动第二个 MPS 重任务；Qwen 真实任务 BLOCKED_BY_ACTIVE_TRAINING

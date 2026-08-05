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

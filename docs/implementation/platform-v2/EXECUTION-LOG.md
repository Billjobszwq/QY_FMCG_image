# Platform V2 — EXECUTION-LOG

> 记录规则：每个命令的命令体、退出码、耗时、结果、制品路径。时间 = 本机 Asia/Shanghai。

## M0 基线盘点（分支创建前，feat/sam-reannotation @ c9998af）

| # | 命令 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | `git status --short` / `git rev-parse HEAD` / `git log --oneline -8` | 0 | 分支 feat/sam-reannotation @ c9998af；工作树：M docs/README.md、M full-project-execution-program.md（用户的新手册索引切换，保留）；?? 新手册文件；?? .quality/ .sam_checkpoints/ .sam_runs/ .superpowers/（不暂存不清理） |
| 2 | 端口探测 `curl -m3` × 8091/8092/8300/8301/8304/8400/8455 | 0 | 8091=404(/)、8092=200、8300=000、8301=000、8304=000、8400=000、8455=404(/) |
| 3 | `curl http://127.0.0.1:8091/v2/health` | 0 | ok=true，cascade_v3，bundle prod_20260804_v4_r2，n_classes=208 |
| 4 | `curl http://127.0.0.1:8092/api/live` | 0 | 返回训练监控 JSON（resnet18 ep80 历史缓存视图） |
| 5 | `python -m pytest -p no:cacheprovider -q` | 0 | **170 passed in 2.91s**（Python 3.13.2，/Users/zhangweiqi/miniconda3/bin/python3） |
| 6 | `verify_bundle('prod_20260804_v4_r2')`（src.models.bundle） | 0 | ok=true，n_files=16 |
| 7 | warehouse 只读计数（`mode=ro` URI） | 0 | 12 表：annotation=170、asset=9、sku_catalog=28、recognition_run=22、model_bundle=1、model_version=3、review_event=5、webhook_event=1、audit_outbox=0、auto_label=0、dataset_version=0 |
| 8 | `du -sh` 制品目录 | 0 | .models 2.9G、.training_data 3.0G、.eval 356M、.sam_checkpoints 484M、.sam_runs 417M、.quality 428K、.review_queue 84K、.warehouse 152K |
| 9 | 必读文件通读 | — | 新手册 622 行、L0 架构 1759 行、CODEX-PROJECT-HANDBOOK 559 行、git-version-control 475 行、training-history、services.json、SAM STATUS/DECISIONS 全部读完 |
| 10 | `git checkout -b feat/usable-platform-foundation` | 0 | 新分支基于 c9998afef5bdda3fdcfea3db5a82892f0be08536；工作树改动随分支保留 |

## M0 提交记录

- 暂存 9 个文档文件（README.md、program.md、新手册、platform-v2 六文档），`git diff --cached --name-only` 核对无制品 → 提交 **f91c0e6**（9 files, +866/-2）

## M1 / W1–W4

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | `pytest tests/platform/test_health_aggregation.py`（W1+W2 TDD） | 0 | <1s | 15 测试全绿；修复点：aggregate 测试需构造 ServiceStatus 而非裸字符串；omlx 探测 `/` 404 → 改 `/health`（200 {"status":"healthy"}，无需 key） |
| 2 | `python3 -m src.platform.api.run --port 8400`（后台真实启动） | 0 | 持续 | `/api/v1/health` 返回 degraded（8300/8301 DOWN 非关键 → degraded；8091/8092/8455 healthy）；日志 /tmp/platform_8400.log |
| 3 | W1+W2 提交 | 0 | — | **97020d6**（src/platform 骨架 + health 聚合 + 15 测试） |
| 4 | `pytest tests/platform/test_legacy_adapters.py`（W4 TDD） | 0 | <1s | 28 测试全绿；修复点：错误需返回 JSON `{"error": kind}`（HTTPException 无 error 字段） |
| 5 | 真实识别 E2E（curl 8400 bridge） | 0 | ~0.5s | 上传 `.training_data/images/train/36619578.jpg` → count=2（罐装雪碧330ml conf 1.0、2L七喜 0.644）；照片1106/190.jpg 与 百事&可口 均 0 检出，直连 8091 同样 0 → 确认是上游 fail-closed 业务行为非 bridge bug |
| 6 | W4 提交 | 0 | — | **54cac63**（legacy.recognition.v2 + legacy.training.monitor adapters + bridge 端点 + 28 测试） |
| 7 | `npm install`（W3，web/） | 0 | ~20s | 69 包；许可证核查：react/react-dom/react-router-dom/vite MIT，typescript Apache-2.0，全部可接受 |
| 8 | `npx tsc -b && npx vite build` | 0 | build 366ms | dist 产物 web/dist/（gitignore）；React 18.3.1 + react-router-dom 6.26.2（HashRouter）+ Vite 5.4.8 + TS 5.5.4 |
| 9 | 浏览器 E2E（Chrome headless，browser-use MCP transport 损坏降级方案） | 0 | ~6s/页 | 6 张截图：/tmp/pv2_evidence/m1_{overview,recognition,training,status,runs,annotation}.png；overview 显示 degraded 横幅+真实服务表；training 显示 8092 真实数据（resnet18 ep80/80、best acc 83.67%、YOLO runs v1–v6） |
| 10 | W3 提交 | 0 | — | **2d9a4ef**（17 files, +2465；.gitignore 补 web/node_modules/、web/dist/） |
| 11 | M1 验收回归 `pytest -q` 全量 | 0 | 2.97s（总 4.4s） | **198 passed**（基线 170 + 平台 28） |
| 12 | M1 验收后 8091/8092 复查 | 0 | — | 8091 /v2/health ok=true（bundle prod_20260804_v4_r2 未动）；8092 /api/live 正常；8400 /api/v1/health 200 |

## M1 验收结论

- 八项验收全过（见 ACCEPTANCE.md M1 矩阵）→ **M1 DONE**

## M2 / W5–W6

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | `pytest tests/platform/test_platform_store.py`（W5 TDD） | 0 | 0.18s | 20 测试全绿（migration 幂等+防篡改、Run/Node/Checkpoint/Job/Attempt/Audit/Usage/Evidence/Asset、备份 integrity_check、重启恢复） |
| 2 | W5 提交 | 0 | — | **46d2f25**；.gitignore 补 `.platform/`；全量 218 passed |
| 3 | `pytest tests/platform/test_m2_contracts.py tests/platform/test_m2_registry.py`（W6 TDD） | 0 | 0.28s | 25 测试全绿（契约 extra=forbid、IAM 双审批分离、Registry 重复/缺 adapter 拒绝、Job 状态机、RequestContext、依赖方向守卫） |
| 4 | 8400 重启 + `curl /api/v1/capabilities` | 0 | ~3s | 返回 2 个 legacy capability；`X-Request-Id` 响应头存在；health 200 degraded |
| 5 | `npx tsc -b && npx vite build` | 0 | 2.27s | 系统状态页新增 Capability 表；Chrome headless 截图 /tmp/pv2_evidence/m2_status.png（真实渲染） |
| 6 | 全量回归 `pytest -q` | 0 | 3.17s | **243 passed** |
| 7 | W6 提交 | 0 | — | **1dc4cc8**（10 files） |

## M2 验收结论

- Registry/契约/Adapters/存储 四项全过（见 ACCEPTANCE.md M2 矩阵）→ **M2 DONE**

## M3 / W7–W11

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | `pytest tests/platform/test_graph_kernel.py`（W7 TDD） | 0 | 0.12s | 11 测试全绿；修复点：重试计数测试自身缺陷（ok handlers 未计数）已修正 |
| 2 | W7 提交 | 0 | — | **fb55084** |
| 3 | `pytest tests/platform/test_cas.py`（W8 TDD） | 0 | 0.11s | 7 测试全绿（去重/原子写/读校验/原图不动） |
| 4 | W8 提交 | 0 | — | **7afa0bf** |
| 5 | `pytest tests/platform/test_w9_graphs.py`（W9 TDD） | 0 | 0.34s | 4 测试全绿；修复点：SQLite 跨线程 → 每线程独立连接（WAL） |
| 6 | W9 提交 | 0 | — | **7450d23**（14 files：modules/fmcg、modules/system_health、composition 根、runs API、bundle） |
| 7 | 8400 切换组合根 `python3 -m src.composition.serve --port 8400` | 0 | ~4s | /api/v1/runs 上线；health 200 degraded |
| 8 | 真实 E2E：upload 36619578.jpg → runs → approve | 0 | ~2s | run ab0946f5：waiting_human → approve → completed；真实识别（罐装雪碧330ml 0.9996、2L七喜 0.6439）；evidence=1；节点链全 completed |
| 9 | system_health_v1 经 API | 0 | <1s | completed；summarize={total:5, unhealthy:[label_studio, ml_backend], overall:degraded}（真实探测） |
| 10 | `npx tsc -b && npx vite build`（W10） | 0 | 359ms | Graph Runs 页：列表/详情/节点时间线/Evidence/人工门按钮 |
| 11 | Chrome headless 截图 | 0 | ~8s | /tmp/pv2_evidence/m3_runs.png：两条真实 completed Run 渲染 |
| 12 | 重启 8400 后 `GET /api/v1/runs` | 0 | — | count=2，Run/Node/Checkpoint 持久化恢复确认 |
| 13 | W10 提交 | 0 | — | **b7513dc** |
| 14 | M3 验收回归 `pytest -q` 全量 | 0 | 3.58s | **265 passed** |

## M3 验收结论

- 九项验收全过（见 ACCEPTANCE.md M3 矩阵；最终 §14 报告于任务结束时输出）→ **M3 DONE**

## M4 Label Studio 闭环（W12–W13）

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | 修 `scripts/start_label_studio.sh`（cd 上跳一级 + `DJANGO_DB=sqlite`）后启动 | 0 | ~20s | LS 1.23.0 原生启动，8300 /health 200；数据目录项目内 `.label-studio/`；admin@qy.local；legacy token 有效 |
| 2 | `legacy.label_studio` capability 注册 + health adapter | 0 | — | capabilities=3；/api/v1/health label_studio=healthy |
| 3 | M4 TDD `tests/platform/test_m4_labeling.py` | 0 | 0.38s | 9 测试全绿：双项目+webhook / blind 0 prediction 红线 / webhook 去重 / 对账一致与丢失检测 / API E2E |
| 4 | 全量回归（修 sqlite WAL 并发后） | 0 | 3.58s | **274 passed**；修复点：`sqlite3.connect(autocommit=True)` 消除隐式长读事务阻塞写者（"database is locked"） |
| 5 | 实测 LS 1.23 import：单次 multipart 仅收一个文件 part | 0 | — | adapter `import_files` 改逐文件循环导入 |
| 6 | 实测 LS 1.23 prediction 端点 | 0 | — | `POST /api/tasks/{id}/predictions/` 404 → 改 `POST /api/predictions/`（task 在 body） |
| 7 | 实测 prediction result 校验 | 0 | — | 嵌套 list 触发 400 "Each item in prediction result…" → `import_photos` 展平修复 + Fake 守卫断言 |
| 8 | 10 张 E2E：`POST /api/v1/labeling/batches` + import（9 张 .field 命中 + 1 张对照） | 0 | 22s | batch f155180f：assisted#10/blind#11 各 10 task；predictions_written=9（真实 8091 识别）；blind preds=0（红线）；reconcile consistent=true、blind_no_predictions=true |
| 9 | webhook 去重实测（重复投递同 payload） | 0 | — | accepted=true → false；event_id 相同；inbox 保留 1 条真实 LS 事件（TASKS_CREATED proj 10，LS 主动投递确认） |
| 10 | Web 标注审核页升级（batches/创建/导入/对账/inbox） | 0 | 0.8s | `tsc --noEmit` 0 + `vite build` 387ms；Chrome headless 截图 /tmp/m4_annotation*.png：双 batch 渲染、reconciled 状态、LS 项目链接 |
| 11 | 50 张扩展：batch M4-trial50 import（9 field + 41 照片1107 对照） | 0 | 111s | batch 334dd7fc：assisted#12/blind#13 各 50 task；predictions_written=9；blind preds=0；reconcile consistent=true |
| 12 | 观察：LS webhook 异步 best-effort | — | — | trial10 TASKS_CREATED 到达；trial50 窗口内未达 → 对账以 LS API 为事实源，不依赖 webhook 单点（设计目标验证） |
| 13 | M4 全量回归 | 0 | 3.58s | **274 passed** |

### M4 事实记录

- 当前模型（cascade_v3 / prod_20260804_v4_r2）仅对三得利货架场景（.field 9 张）有检出；照片1106/1107/百事&可口 在 conf 0.25 与 0.1 均 0 检出 → 50 张 batch 中 41 张为"无预标注对照"，如实呈现模型覆盖；扩充训练数据属 M5。
- 人工标注/双审/仲裁未执行：按红线暂停请求授权。

## M5 数据集训练治理（W14）

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | M5 TDD `tests/platform/test_m5_training_gov.py` | 0 | 0.4s | 14 测试一次全绿：split guard / snapshot hash / gates / dry-run / 授权门 / 发布分离 / 晋级门 / 统一评估 / API E2E |
| 2 | store migration 003（dataset_snapshot/training_run/platform_flag） | 0 | — | training_authorized 默认 false（fail-closed） |
| 3 | `src/modules/training_gov/` + `src/platform/api/training.py` + 组合根接线 | 0 | — | 平台只承载 HTTP 边界；治理逻辑在 modules 域 |
| 4 | 全量回归 | 0 | 3.76s | **288 passed** |
| 5 | 真实 API 验证（8400）：gates/snapshot/dry-run/无授权 start | 0 | — | gates 阻断（training_authorized=false）；snapshot 072aeebebdb9 注册；dry-run 3d3560b5 命令回显；无授权 start 403 |
| 6 | Web 训练工作台（为什么不能训练/还差什么/批准后命令） | 0 | — | tsc 0 + build；截图 /tmp/m5_training.png |
| 7 | M5 提交 | 0 | — | **cef025a**（10 files，1102 insertions） |

### M5 事实记录

- truebox 评估已是修正版：one-to-one 匹配 + 真实 FP/photo 预算扫描 + 互斥错误账本；TopK 不得用于晋级。
- dry-run 只产计划不执行；start 需 flag+IAM admin 双校验；发布仅 completed_candidate 且独立 admin 审批；auto_switch 不进新平台。
- 训练启动未执行：按红线暂停请求授权（training_started=false 冻结不变）。

## M6 PostgreSQL + 可靠 Worker（W15）

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | M6 TDD `tests/platform/test_m6_worker.py` + `test_m6_pg_migration.py` | 0 | 0.49s | 22 passed + 1 skipped（PG 门控）：成功/重试/dead-letter/崩溃恢复不重复/取消/背压/吞吐基线/CAS 校验备份恢复水位/分享 token/CORS/Jobs API E2E |
| 2 | store migration 004（job lease/attempt 列 + share_token 表） | 0 | — | 开发库重启后自动应用 |
| 3 | `src/platform/worker.py` RecoverableJobWorker | 0 | — | 原子认领+lease；requeue 退让（同轮不重领）；重试耗尽/lease 过期耗尽 → dead_letter；背压 max_concurrent |
| 4 | CAS 加固：verify_all/backup/restore/disk_watermark | 0 | — | restore 先落临时区逐文件校验再并入（fail-closed） |
| 5 | 安全加固：CORS 白名单（PLATFORM_CORS_ORIGINS）+ 分享 token（scope/有效期/吊销）+ 敏感动作审计 | 0 | — | CSRF：状态变更均 JSON POST；非白名单 Origin 预检被拒 |
| 6 | 全量回归 | 0 | 4.12s | **310 passed，1 skipped**（PG 门控） |
| 7 | 重启 8400 真实 E2E（curl） | 0 | — | echo job 提交→poll→succeeded（attempt 恰 1）；未知 kind 400；取消 200→再取消 409；stats dead_letters=0；audit_event 5 条（job.submit/cancel、share.create/revoke） |
| 8 | 分享链接真实 E2E | 0 | — | create→check valid→错误 scope 403→revoke→check 403（fail-closed） |
| 9 | CAS 备份恢复演练（真实开发库） | 0 | — | verify_all ok（2 blob）；backup /tmp/m6_cas_backup.tar.gz（archive_sha256 ac3f39e0…）；restore→新目录 verify ok；水位 free_fraction=0.753 未超 |
| 10 | PG 迁移脚本 `scripts/migrate_sqlite_to_pg.py` | 0 | — | 单次不双写；逐表行数+规范化 sha256 核对；psycopg 缺失时明确报错；真实 PG 运行门控于 PLATFORM_TEST_PG_URL |
| 11 | 吞吐基线测试 | 0 | — | 100 job <10s 软上限（实测 <1s） |
| 12 | Web 未回归验证 | 0 | — | /#/training 截图 /tmp/m6_training.png 正常渲染 |
| 13 | 授权后：`brew install postgresql@16` + `pg_ctl start` + createdb platform_drill | 0 | — | PostgreSQL 16.14（Homebrew，演练集群 /opt/homebrew/var/postgresql@16）；5432 accepting connections |
| 14 | `pip install psycopg[binary]`（3.3.4）后真实迁移核对 | 0 | 0.17s | **16/16 表 match=true**（逐表行数 + 规范化 sha256 双侧一致；含 graph_run 2/node_execution 9/audit_event 7/schema_migrations 4）；不双写；SQLite 原库保留 |
| 15 | PG 门控测试（PLATFORM_TEST_PG_URL 设置） | 0 | 0.13s | 5 passed（含真实 migrate 往返） |

### M6 事实记录

- PG 演练（已授权）：brew postgresql@16 本机演练集群；单次迁移 16/16 表计数+哈希一致；演练库 platform_drill；生产切换（DATABASE_URL 指向生产 + 服务重启）仍为独立授权点，未执行。
- 8091/8092 未触碰；生产 bundle 未触碰；三冻结值不变。

## 2026-08-05 独立审计纠偏（只读审查 + 文档更新）

> 本节不改写 M5 历史执行记录。它记录随后发现的验收口径错误；以当前代码与实时数据证据为准。

| # | 核验 | 结果摘要 |
|---|---|---|
| 1 | `git status --short --branch` / `git log` | `feat/usable-platform-foundation@9db9946`；未跟踪 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/` 保留、不处理 |
| 2 | 主机全量测试 | **310 passed, 1 skipped**；沙箱的 MPS 不可见不代表 Mac 主机回归 |
| 3 | 主机 `GET 8400/api/v1/health` | degraded；8091/8092/8300/8455 healthy；8301 unavailable |
| 4 | 真实浏览器逐页审查 | 7 页均可打开且无明显控制台错误；缺统一待办/业务主线；Assets 错报 CAS 未启用；Training 显示演示快照、无效命令与旧 phase |
| 5 | truebox 代码/测试审查 | `recall_at_fp` 为逐图 top-K proposal；测试锁定 TopK；不是全局阈值真实 FP/photo；M5 REOPENED |
| 6 | 训练命令对照 | dry-run 生成 `--dataset`、`--budget-minutes`；`train_v1.py` argparse 不支持，命令不可执行 |
| 7 | 平台开发库只读查询 | 唯一 Snapshot 是 2 train + 1 val 演示 manifest；4 个重复 dry-run；`training_authorized=false` |
| 8 | Graph Kernel 审查 | GraphDefinition 仅 nodes tuple，Engine 固定 for-loop；max_loops 是 attempt 上限，不是真实 feedback loop |
| 9 | 人工/质量现状 | review queue 250/250 pending、final_box 0；qa_v3 120 张为 accept 92/manual 28/reject 0，无人工金标准混淆矩阵 |
| 10 | 数据池清点 | batch1 2,947；batch2 6,510/174,249 点；batch3 22,664（旧 clean 22,659/bad 5）；本地 213+489+341 货架样板、240 标准图、9 field；存在已知重叠，唯一总量待 SHA+pHash 台账 |
| 11 | E2 audit | train 2,000/50,018 框；val 300/7,975 框；manifest `35f70f0a0cfd53b8`；当前为点锚合成框，非人工 truebox |
| 12 | 文档交付 | 新建 `2026-08-05-unified-management-all-photo-training-execution-manual.md`；更新 README/STATUS/PLAN/ISSUES/ACCEPTANCE；未改业务代码、未启动训练、未切模型、未删除文件 |

### 审计结论

- 平台原型可运行，不能宣布统一管理完成。
- M5 由 DONE 改为 REOPENED；当前训练为 NO-GO。
- 新手册授权范围：所有 P0 与数据/MPS 门通过后可执行 1ep smoke 和 3ep pilot；T2 后必须停止，10ep/发布/生产切换需新授权。

## U0 事实恢复与工作台账（2026-08-05 续，分支 feat/unified-workbench-training-readiness）

| # | 命令/动作 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | §1 权威文件全量通读（非摘要） | — | 新手册 451 行；L0 架构 1759 行；CODEX-PROJECT-HANDBOOK 559 行；training-history-and-decisions 148 行；final-training-execution-gate 413 行；SAM 重标注计划 413 行；platform-v2 六治理文档（ISSUES PV2-001～024 已被审计更新） |
| 2 | `git status` / `git rev-parse HEAD` / `git log` | 0 | 基点 `feat/usable-platform-foundation@9db9946`；工作树：9 个审计文档 M + 未跟踪制品 `.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/`（保留不动） |
| 3 | 服务探测（正确端点） | 0 | 8091 `/v2/health` ok=true（prod_20260804_v4_r2）；8092 `/api/live` UP；8300 `/health` UP；8455 进程在；8301 DOWN；8400 degraded（ml_backend 非关键） |
| 4 | 平台开发库只读查询 | 0 | snapshot 唯一=072aeebebdb9（2 train+1 val 演示 manifest）；`training_authorized=false`；training_run 4 条（重复 dry-run）；audit_event 7；`.review_queue` 250 条 pending |
| 5 | 照片池只读清点 | 0 | 照片1106=213、照片1107=489、百事&可口=341、搭建初期P1≈240 标准图、.field=9；协议文件 6 个；.datasets 4 目录；唯一总量待 U3 SHA 台账 |
| 6 | `pytest -p no:cacheprovider -q` 全量基线 | 0 | **310 passed，1 skipped**（4.52s） |
| 7 | `git checkout -b feat/unified-workbench-training-readiness` | 0 | 基于 9db9946；审计文档改动随分支保留 |
| 8 | Bug 代码定位确认 | — | `src/eval/truebox_eval.py` `recall_at_fp` 逐图 `preds[:K]` TopK；`src/modules/training_gov/service.py` dry-run 生成 `--dataset`/`--budget-minutes` 且 `mps_g0=sys.platform=="darwin"`；`train_v1.py` argparse 支持 --data-yaml/--run-name 等，不支持 --dataset/--budget-minutes |
| 9 | 治理文档交付 | — | 新建 `IMPLEMENTATION-LIST.md`（U0–U5/T0–T2 全任务）；DECISIONS 追加 PV2-D-009～017；STATUS 切新分支；本节日志追加 |

### U0 提交（文档小 commit，不含业务代码）

- 暂存范围：9 个审计文档 M + IMPLEMENTATION-LIST 新增；`git diff --cached --name-only` 核对后再提交；不 `git add .`。
- 已提交 **32e8db0**（11 files，+718/-45）。

## U1 训练真实性 P0（UMT-001～008 TDD，进行中）

| # | 命令/动作 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | U1-001/002：红测试 `tests/platform/test_umt001_true_fp.py` 5 项 RED → 实现 → 全绿 | 0 | recall@FP 改全数据集统一阈值扫描；错误账本互斥分类 + FP 守恒断言；内建参考实现互验；旧锁定 TopK 测试按审计口径改写；提交 **0908127**（316 passed） |
| 2 | U1-003：红测试 `tests/platform/test_umt002_command.py` 5 项 RED → 实现 → 全绿 | 0 | train_v1 抽离 build_arg_parser（allow_abbrev=False）+ --parse-check；dry-run 命令只用真实参数并入库前 parser 预检；提交 **433f995**（321 passed） |
| 3 | U0-2/U1-004：红测试 `tests/platform/test_u0_snapshot_marking.py` 3 项 RED → 实现 → 全绿 | 0 | migration 005（trainable/status_note）；mark_snapshot_demo 幂等 + audit；gates/dry_run 排除不可训练 Snapshot；全量 **324 passed + 1 skipped** |
| 4 | 真实开发库标记演示 Snapshot | 0 | 072aeebebdb9（e2_product_pilot@v1）trainable=0 + 备注；audit snapshot.mark_demo；gates registered_snapshots=0、can_train=false；行与 manifest 保留未删除 |
| 5 | U1-005：红测试 `tests/platform/test_umt003_snapshot_builder.py` 8 项 RED → 实现 → 全绿 | 0 | 新增 `src/modules/training_gov/builder.py`（逐文件校验/SHA+pHash 去重/五键守卫/protocol_guard/staging+data.yaml/拒绝覆盖）；service.build_and_register_snapshot；POST /snapshots → 410，新增 POST /snapshots/build；test_m5 E2E 改走真实 builder（修正：val 需独立门店满足 split 守卫）；提交 **50e39ff**，全量 **332 passed + 1 skipped** |
| 6 | U1-006：红测试 `tests/platform/test_umt005_mps_g0.py` 7 项 → 实现 → 全绿 | 0 | 新增 `src/modules/training_gov/mps_gate.py`：arm64/torch MPS built+available/1024² matmul/Conv2d 前向/禁 PYTORCH_ENABLE_MPS_FALLBACK/pmset AC/sysctl 内存+swap/磁盘，全部实测；dry_run 写入 mps_g0_report 证据；start_training 对 G0 失败 raise；主机实测（AC、MPS 真实运算）全绿；提交 **7cd3c81**，全量 **339 passed + 1 skipped** |
| 7 | U1-007：红测试 `tests/platform/test_umt006_auth.py` 6 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/auth.py`：pbkdf2 口令哈希/登录 session（migration 006 auth_sessions）/session 绑定 CSRF；training+jobs+share 写端点 require_principal（401/403 fail-closed），X-Role/X-Actor 不再作为身份依据；E2E（test_m5/test_m6）改走登录流；顺修 DryRunBody imgsz 默认 1280→960；提交 **4085023**，全量 **345 passed + 1 skipped** |
| 8 | U1-008：红测试 `tests/platform/test_umt007_job_semantics.py` 5 项 RED → 实现 → 全绿 | 0 | service.approve_plan（只落状态，worker.submitted==[]）与 enqueue_training_job（需 approved+授权+G0；提交 training.run job）；Worker handler 真实子进程留 PID/日志（PLATFORM_RUNS_ROOT/.runs/<run_id>/attempt_N.log）；migration 007 training_run.job_id；API /approve-plan /enqueue；全量 **350 passed + 1 skipped** |
| 9 | U1-009/U0-3：前端登录 + 训练页七分区 + 浏览器 E2E | 0 | 红测试：/auth/me 返回 csrf_token（页面刷新恢复 CSRF）→ 实现；api.ts login/me/logout + CSRF 封装 + approvePlan/enqueue/jobs；App.tsx topbar 登录表单；Training.tsx 七分区（演示快照标不可训练/可训练/计划/已批准/活动 Job 显 idle/历史/生产）；`tsc --noEmit` + vite build 42 modules；重启 8400（旧进程无 auth router 的旧代码占端口，kill 后以 src.composition.serve + PLATFORM_USERS 启动）；browser E2E：未登录表单→admin 登录 200→已登录态→七分区全显→idle 横幅→console 无 error；截图 `.eval/training_login_check_{1..4}_*.png`；全量 **351 passed + 1 skipped**；提交 **87f16d5** |

### U1 结论

- UMT-001～008 全部落地（008 文档一致性由 U0 承担）；U1-001～009 全 DONE。
- 三冻结值保持：production_switch=false、training_started=false、deleted_files=false。
- 下一步：U2 统一管理 MVP（角色首页/统一任务中心/真实数据中心）。

## U2 统一管理 MVP（进行中）

| # | 事项 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | U2-1：红测试 `tests/platform/test_u2_workitems.py` 5 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/api/workitems.py`：聚合真实来源（PLATFORM_REVIEW_QUEUE 默认 `.review_queue/review_queue_diag_v1.json` 250 pending 审核 + list_training_runs + jobs queued/running/failed + labeling 批次）；summary 含 pending_review/todos/active/blocked/next_steps；Overview.tsx 改角色首页（待办/审核/活动/阻断卡片 + 阻断横幅 + 下一步 + 任务列表，15s 轮询）；真实库 GET /api/v1/workitems 返回 256 条（250 审核+4 训练+2 标注）；浏览器 E2E：254 待办/250 审核/阻断横幅正确，截图 `.eval/workbench_home_*.png`；全量 **356 passed + 1 skipped**；提交 **516042b** |
| 2 | U2-3：红测试 `tests/platform/test_u2_recognition_tasks.py` 6 项 RED → 实现 → 全绿 | 0 | migration 008 recognition_task 表 + store create/get/list_recognition_task；新增 `src/platform/api/recognition_tasks.py`：run_recognition_batch 四入口共享服务层（单文件/批量 upload、URL、API/Agent 同端点，身份来自服务端 session）；MAX 32 文件/25MB；RecognitionAdapterError 收集 errors；Recognition.tsx 四分区（单文件即时/批量/URL/任务历史）；浏览器 E2E：真实照片（照片1106/1.jpg+2.jpg）批量识别 200（entry=batch_file/completed/admin/耗时 294ms/bundle prod_20260804_v4_r2，检出 0 属近景 fail-closed 正常），截图 `.eval/recognition_unified_batch_verify.png`；全量 **362 passed + 1 skipped**；提交 **fc4ddfe** |
| 3 | U2-5：红测试 `tests/platform/test_u2_idempotency_paging.py` 7 项 RED → 实现 → 全绿 | 0 | migration 009：recognition_task 增 idempotency_key + 唯一索引；upload/url 读 Idempotency-Key，重复请求重放同一任务（不新建）；任务列表 limit/offset/status + 全量 count；workitems limit/offset/kind/status；重复 enqueue 返回同一 Job（不重复提交）；前端 crypto.randomUUID 幂等键 + 历史筛选分页；浏览器 E2E：请求头含 Idempotency-Key（16d1e7d6…）+ 真实照片批量识别成功 + 筛选分页可用，截图 `.eval/u25_recognition_paging_verify.png`；重启 8400（PID 13849，migration 009 自动应用）；全量 **369 passed + 1 skipped**；提交 **f0e87c1** |
| 4 | U2-4：红测试 `tests/platform/test_u2_vocabulary.py` 3 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/vocabulary.py`：UNIFIED_STATUS（11 个业务词→todo/active/done/blocked）+ status_text 五类映射（training/job/human_review/recognition/labeling/graph_run，未知状态 fail-closed 回显）；workitems 每条增 status_text/stage，任务标题改中文；Overview 状态列业务语言 + 「高级详情」details 折叠（raw_status/photo_id/run_id 只进折叠区，默认折叠）；Recognition/Training 状态 pill 与筛选选项中文；重启 8400（PID 20041）；浏览器 E2E：工作台 50/50 行中文「待人工审核」、高级详情默认折叠（展开含 raw_status/photo_id）、识别/训练页中文、三页 console 无错，截图 `.eval/u24_business_language_overview.png`/`.eval/u24_business_language_recognition.png`；全量 **372 passed + 1 skipped**；提交 **3710c0a** |
| 5 | U2-2：红测试 `tests/platform/test_u2_assets.py` 4 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/api/assets.py`：/api/v1/assets/summary（真实台账+sha_dedupe+disposition_report）与 /api/v1/assets（source_id 筛选+分页+每行 purposes）；Assets.tsx 移除"CAS 未启用"占位：卡片 38284 引用/30459 SHA 唯一/6560 重复组/4684 冻结/1239 待标注（全真实），用途分布中文折叠区，来源筛选 photo1106=213 全待标注，分页可用；重启 8400；浏览器 E2E 全绿、console 无错，截图 `.eval/u22_assets_overview.png`/`.eval/u22_assets_filter_photo1106.png`/`.eval/u22_assets_usage_expanded.png`；全量 **400 passed + 1 skipped**；提交 **e2c32b2**；U2 全部完成 |

## U3 全照片资产化（进行中）

| # | 事项 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | U3-1：红测试 `tests/platform/test_u3_inventory.py` 6 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/assets/inventory.py`：手册 §5.1 全部 11 个来源族只读扫描器（manifest_photos_dict/sha_dict/photos_list/directory/protocol_dir）；真实库核验 batch1=2947/batch2=6510/batch3_clean=22659 与手册 §5.1 精确一致；total_raw=38284（含重复，显式标注禁止当唯一数）；下载失败 0；发现 manifest 已内置 SHA（U3-3 去重无需重哈希 batch1/2/3）；全量 **378 passed + 1 skipped**；提交 **4384b71**；证据 `.eval/u3/source_scan_v1.json`（gitignore 本地） |
| 2 | U3-2：红测试 `tests/platform/test_u3_ledger.py` 6 项 RED → 实现 → 全绿 | 0 | migration 010：`source_asset_inventory_v1`（UNIQUE(source_id,source_uri) + BEFORE DELETE/UPDATE 触发器 RAISE 不可变）+ store register/count/list_inventory_assets；新增 `src/platform/assets/ledger.py` build_ledger_from_scan（manifest 用现成 SHA、目录照片现场 hashlib 哈希、protocol 平行列表）；真实库建账 **38284 条 == total_raw 守恒**，38284 条全带 64 位 SHA，重跑幂等 0 新增，耗时 6.5s；8400（PID 20041）迁移自动应用、页面 200；全量 **384 passed + 1 skipped**；提交 **8899d25**；证据 `.eval/u3/ledger_build_v1.json` |
| 3 | U3-3：红测试 `tests/platform/test_u3_dedup.py` 5 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/assets/dedup.py`：SHA 精确去重（GROUP BY 只产出分组不删台账行）+ 自实现 DCT-pHash（PIL+scipy，无新增依赖，汉明≤ 8 union-find，按唯一文件扫描）；真实库：**38284 引用→SHA 唯一 30459**，精确重复组 6560，近重复组 52（扫 1288 本地文件），下载失败 0，耗时 89s；报告显式声明唯一数口径；全量 **389 passed + 1 skipped**；提交 **e44c9e1**；证据 `.eval/u3/dedup_report_v1.json` |
| 4 | U3-4：红测试 `tests/platform/test_u3_disposition.py` 7 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/assets/disposition.py`：7 用途规则引擎（detector_training/classifier_retrieval/packaging_unknown_sku/quality_negative/eval_frozen/to_label/rejection_evidence）；全部 frozen protocol 只评估不训练；坏样本禁进训练；真实库 **38284 行全部有用途（0 空档），frozen→training 泄漏 0**；分布 detector 候选 32116/classifier 32356/包装版本 427/质量负 5/评估冻结 4684（gold_v2 1203+gold_holdout 977+dev_v2 801+dev_v1 800+diagnostic 500+calibration 403）/待标注 1239/拒绝证据 5；全量 **396 passed + 1 skipped**；提交 **8f40ea5**；证据 `.eval/u3/disposition_report_v1.json` |
| 5 | U3-5：红测试 `tests/platform/test_u3_qpol_v2.py` 7 项 RED → 实现 → 全绿 | 0 | migration 011 `quality_decision_v1`（追加式不可变触发器；SHA/策略版本/分数/阈值/自动结论/人工结论/模型版本/证据全字段）；新增 `src/platform/quality/qpol_v2.py`：11 维（斜拍/反光/翻拍/屏摄/摩尔纹/模糊/大头照误导/裁切/遮挡/场景/价签），blur（Laplacian 方差）/reflection（近白占比）启发式 heuristic_v1，其余 9 维无分析器一律 waiting_human；整体判定任一 fail→fail，否则 waiting_human（禁止伪造 pass）；真实照片1106 冒烟 10 张：5 fail/5 waiting_human/0 pass（诚实口径）；全量 **407 passed + 1 skipped**；提交 **bc97de6** |
| 6 | U3-6：红测试 `tests/platform/test_u3_gold.py` 6 项 RED → 实现 → 全绿；再补 API 层 `tests/platform/test_u3_gold_api.py` 5 项直接绿 | 0 | migration 012：`quality_gold_v1`（队列，sha256 UNIQUE）+`quality_human_v1`（人工结论，同 SHA 仅一次）均 BEFORE DELETE/UPDATE 触发器 RAISE；新增 `src/platform/quality/gold.py`：分层轮转建队（只收 directory 来源且本地文件存在，manifest-only 不入队）/状态由 human 行推导（无 UPDATE，未完成只能 waiting_human）/混淆矩阵只算有人工结论的对（无自动结论记 none）；新增 `src/platform/api/gold.py`：status/confusion 只读，build/verdict 强制服务端 session+CSRF，reviewer 取登录身份（伪造 X-Actor 拒绝）；数据中心页新增金标准分区（卡片/表格/登录后通过-不通过/混淆矩阵）；真实库登录建队 **500**（fail 层 5+无结论层 495），幂等重跑 0，waiting_human=500；浏览器 E2E：未登录 500/0+「登录后审核」，登录提交后 499/1+不可改，console 无错；全量 **418 passed + 1 skipped**；提交 **98fa4cc**；截图 `.eval/u36_gold_before_login.png`、`.eval/u36_gold_after_verdict.png` |

## U4 质量过滤与 SAM 标注闭环（进行中）

| # | 事项 | 回滚 | 证据/结果 |
|---|---|---|---|
| 1 | U4-1：红测试 `tests/platform/test_u4_sam_lineage.py` 4 项 RED → 实现 → 全绿 | 0 | migration 013 `sam_lineage_v1`（point→prompt→mask→box 全字段：正/负点、粗 ROI、config 版本、模型/checkpoint SHA、mask SHA/路径、decision、tight_box、selection_reason、rules_v1、reject_reasons，BEFORE DELETE/UPDATE 触发器 RAISE）；新增 `src/platform/annotate/sam_pipeline.py`：复用 sam_assist prompts/硬约束筛选（面积/长宽比/含正点/多连通域/触边/重叠）/rules_v1 评分，默认 Hiera Small，仅无合格候选的实例升级 Base+ 一次，仍失败→manual_required（tight_box 恒 NULL，禁止比例框回退）；SAM 推理在隔离 .venv_sam worker（MPS fail-closed）；真实冒烟（scripts/run_u4_sam_smoke.py，2 照 8 点，.field 真实点）：**2 accepted（Small 直出 tight box）/6 manual_required（升级 Base+ 仍无合格，拒绝原因 multi_component×8/missing_positive×2/touches_roi_boundary×2/area_out_of_range×1）**；全量 **422 passed + 1 skipped**；提交 **7cffebf**；证据 `.eval/u4/smoke_report_20260805_130608.json`（gitignore 本地） |
| 2 | U4-2：红测试 `tests/platform/test_u4_review_flow.py` 9 项 RED → 实现 → 全绿；再补 API 层 `tests/platform/test_u4_review_api.py` 5 项直接绿 | 0 | migration 014：`review_task_v1`（导入即冻结，BEFORE DELETE/UPDATE 触发器 RAISE）+`review_event_v1`（claim/review/blind_sample 追加式事件）；状态机全部由事件推导（无 UPDATE）：单审一次终态/双审框一致终态/分歧升仲裁（role=arbiter 一锤定音）/同 actor 二次提交拒绝/已认领不得二次认领；10% 盲抽 seed 可复现；导出 JSON 附 SHA256；`src/platform/api/review.py`：status 公开只读，tasks/claim/submit/export 强制 session+CSRF，actor 取登录身份（伪造 X-Actor 401），仲裁仅 admin（operator 403）；数据中心页新增审核区块（状态卡片/任务表/认领/提交框/仲裁/导出）；真实队列口径：幂等键 (photo_id,sha256,review_mode) 支持盲抽项与双审项同照片；全量 **436 passed + 1 skipped**；提交 **cc190a8**；截图 `.eval/u4/u42_review_ui_250pending.png`、`.eval/u4/u42_review_ui_claimed.png` |
| 3 | U4-3：`.review_queue/review_queue_diag_v1.json` 250 条 pending 真实接入生产库 | 0 | 导入前先备份生产库（`.eval/u4/platform_backup_before_u43.sqlite`，backup API integrity_check ok）；`scripts/import_u4_review_queue.py` 只读队列 JSON 追加写入：**imported=250（200 double_review+50 blind_manual）、rerun_imported=0、total=250**；浏览器 E2E（admin 已登录）：队列总数 250/待认领 250/终态 0，认领首条后 249/1、状态已认领待审、认领人 admin，console 无错；队列仍全部 pending，无任何伪造完成；提交 **3e1e4a0** |
| 4 | U4-4：红测试 `tests/platform/test_u4_batches.py` 4 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/annotate/batches.py`：阶梯 BATCH_LADDER=(100,500,2000,-1)，批次标签复用 review_task_v1.protocol 列（不新增表）；门控：未完成→waiting_human（禁止伪造通过）、双审一致率（未经仲裁终态/全部双审终态）<0.8→gate_failed 永久拒扩展、达标→ready 取下一阶梯；幂等重入已存在批次不受门控阻止；status API 增加 batch_plan，UI 显示批次进度；真实库诚实口径：诊断批 250 条 finalized=0 → `waiting_human`（curl 机器证据：`"n_finalized":0,"status":"waiting_human"`）；全量 **442 passed + 1 skipped**；提交 **6baa389**；剩余：真实人工完成 250 诊断批后才能扩展 100 张 E2E |

## U5 Graph+Loop v2（进行中）

| # | 事项 | 回滚 | 证据/结果 |
|---|---|---|---|
| 1 | U5-1：红测试 `tests/platform/test_u5_loop_kernel.py` 6 项 RED → 实现 → 全绿 | 0 | 新增 `src/platform/kernel/loop.py`：EdgeSpec(next/on_fail/feedback + when 标签)/GraphV2（frozen，图结构随 run 持久化可跨实例恢复）/LoopEngine：条件路由 router(output,state)→when 匹配，未匹配 fail-closed（no_edge）；feedback 回跳增轮，超 max_rounds→failed+stop_reason=budget_rounds；人工门复用 HumanGateRequested，waiting_human 后 approve 可由全新引擎实例续跑，reject 终态；decision trail（轮次/节点/决策/原因/下一节点）全部经 checkpoint 持久化可回放；sequential v1（GraphEngine）一行未动；全量 **448 passed + 1 skipped**；提交 **ef1b4e1** |
| 2 | U5-2：红测试 `tests/platform/test_u5_real_loop.py` 4 项 RED → 实现 → 全绿；生产库真实 E2E | 0 | 新增 `src/platform/loops/pipeline_v2.py`（photo_pipeline_v2：select→quality(qpol_v2 真实落库)→has_fails 回流 select / clean→review(人工门)→assemble→recognize(8091 真实识别)）+ `LoopNodeContext`（跨节点共享状态/门状态查询）+ `src/platform/api/loops.py`（start/gate 仅 admin session+CSRF）；生产库首跑实测反转：photo1106 三轮均含 fail（26 条 quality.fail 审计）达轮次预算，bad_samples 启发式未判 fail 诚实 waiting_human——按真实数据分工重跑：**Run A bad_samples：waiting_human→全新引擎实例 approve→completed（组装 5 张，识别 8091 真实调用）；Run B photo1106：feedback 回流×2→budget_rounds 停止**；四类 E2E 事件（条件分支/人工暂停恢复/质量失败回流/预算停止）全部真实发生；执行前备份生产库；证据 `.eval/u5/u52_real_loop_evidence_*.json`；全量 **452 passed + 1 skipped**；提交 **b32fd2c** |
| 3 | U5-3：Loop v2 UI + 浏览器 E2E | 0 | GraphRuns 页新增 Loop v2 区块：启动表单（source/批量/最大轮次，仅 admin）、run 表（状态中文/轮次/停止原因/等待项+下一节点/成本）、详情轨迹表（轮次/节点/决策中文/决策原因/下一节点）、人工门批准/拒绝按钮；API 增 cost_nodes/cost_detail；浏览器 E2E（admin 登录）：列表 4 run 状态齐全，点开 completed run 轨迹 6 行决策原因齐全，**UI 点击批准 waiting_human run（session+CSRF）→真实续跑→完成**，console 无错；证据 `.eval/u5/u53_browser_evidence.json`（截图工具在本应用持续超时，沿用 U4-3 口径以 JSON+文本为机器证据）；提交 **53e4b4b** |

## T0 MPS 预检（完成，d58d554）

| # | 事项 | 回滚 | 证据/结果 |
|---|---|---|---|
| 1 | T0：红测试 `tests/platform/test_t0_preflight.py` 12 项 RED → 实现 `src/training/t0_preflight.py` → 全绿；再补真实格式红测试 1 项（pmset -g therm 无 warning 三行 Note）→修复 parse_thermal | 0 | pick_resolution（仅 768/960/1024，禁 1280；ips 优/平局峰值内存低者胜）、budget_estimate（停止线 6h 墙钟/8192MB swap/热限流即停）、parse_thermal（fail-closed） |
| 2 | 真实硬件预检脚本 `scripts/run_t0_mps_preflight.py`（caffeinate -i 包裹）两跑 | 0 | G0 ok=true（复用 run_mps_g0）；照片1106 等间隔采 160 张三档 YOLO 前向：**两跑均选 768（8.5/8.19 img/s，peak 0.306 GB；960=8.26/7.99，1024=7.97/7.77）**；thermal 前后无 warning；服务 8091 /v2/health、8092 /api/live、8400 /api/v1/health 前后均 200；预算：T2 1000张×3ep@8.5≈366s 不超限；no_training_executed=true；证据 `.eval/t0/t0_preflight_evidence_20260805_150704.json`、`..._151618.json` |
| 3 | 首跑发现并修复两处证据失真（诚实口径） | 0 | ① pmset -g therm 无 warning 时只输出三行 Note（无 key=value），旧 parser fail-closed 误判限流致 benchmark 误停——新增红测试后修复；② mps_gate swap 解析不兼容 macOS 15 `total = 12288.00M`（等号两侧空格+G 单位）致解析全 None 掩盖真实 swap——新增 4 项红测试（TestParseSwapUsage）抽出 parse_swap_usage 修复；修后实测 swap used=10867.44MB **>8192 停止线，证据如实 exceeds_stop_line=true**（训练启动授权前必须处置） |
| 4 | run 目录拒覆盖与服务健康（T0-3） | 0 | 既有测试 tests/unit/test_run_overwrite_guard.py（train_v1.py 拒绝覆盖）继续绿；服务健康快照写入证据 services_before/after |

全量回归 **469 passed + 1 skipped**（+13 t0_preflight +4 parse_swap_usage）；提交 **d58d554**。T0 退出门达成：G0 证据✓、合法 dry-run（U1 dry_run 测试链）✓、预算估算与停止线✓、无训练结果污染✓；未默认 1280（实测选 768）✓。

## VLM 专项基线（2026-08-06，Qwen3-VL 级联 Task 0 事实对账，全部只读）

| # | 事项 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | Git 状态 | 0 | 分支 `feat/unified-workbench-training-readiness`，HEAD=**4f7bfdd9b136cb611843cc72f3ae80e1c9ec525c**（与指令声明基线一致）；近链：4f7bfdd（Qwen 设计文档）← f0a7fd1（监控升级）← b07ff0a ← e59f683（SAM 精修）← 5cec9f9（质量门禁） |
| 2 | 工作树 | 0 | 仅 4 个未跟踪保护目录：`.quality/ .sam_checkpoints/ .sam_runs/ .superpowers/`（保留不暂存）；无其他修改 |
| 3 | sku_v7_sam 训练进程 | 0 | **PID 90423 运行中**（另 caffeinate PID 90425），已运行约 21h；命令：`python3 -m src.training.train_v1 --model .models/sku_v4/weights/best.pt --data-yaml .datasets/sam_refined_full_v1/data.yaml --run-name sku_v7_sam --epochs 120 --patience 10 --batch 4 --imgsz 960 --device mps --lr0 0.0005 --seed 0`；日志尾 epoch 31/120 进行中 |
| 4 | results.csv 解析（只读，当前 30 条完成 epoch） | 0 | **mAP50 best=0.6265 @epoch 30**（仍在创新高）；precision best=0.6104 @epoch 23；recall best=0.6129 @epoch 18；最新 epoch30：P=0.5880/R=0.6058 |
| 5 | 系统资源 | 0 | swap used≈7592MB/9216MB（在 8192 停止线内，训练 RSS≈6.4GB）；AC 电源≈78% 充电中；训练正常 |
| 6 | Ollama/MPS 环境 | 0 | Ollama.app 进程在但 ollama CLI 不在 PATH（无加载模型）；omlx-server 运行中；不得新启第二个 MPS 重任务 |
| 7 | 服务状态 | 0 | 8091 识别入口、8092 训练监控、Label Studio 保留不动；本轮改造不得影响；新级联 shadow 默认（production_switch=false 冻结不变） |
| 8 | 测试基线 | 0 | 全量 **505 passed, 1 skipped**（本轮开工前基线） |
| 9 | 本轮允许的工作 | — | Task 0–18 非重计算代码：架构/契约/Graph/API/Web/数据构建器/训练启动器/资源管理器/单元+契约+fake mock 集成测试/文档 runbook |
| 10 | 本轮禁止的工作（fail-closed） | — | Qwen 权重下载、MLX 真实安装、Qwen 真实前向/微调、真实大规模 shadow、生产模型切换、kill/干扰训练、启动第二个 MPS 重任务、PYTORCH_ENABLE_MPS_FALLBACK、把运行中训练判定为可发布；真实重任务统一标记 **BLOCKED_BY_ACTIVE_TRAINING** |
| 11 | 治理偏差登记 | — | ISSUES.md 追加 VLM-ISSUE-001~006（STATUS 与实际训练冲突/optimizer=auto 忽略 lr0=0.0005/934 tilt 缺人工金标准/SAM 96.5% 仅几何通过/Qwen 未安装/真实 MLX 被资源门禁阻断） |

## VLM 专项实施记录（Task 1–18，训练中不扰，真实重任务 BLOCKED_BY_ACTIVE_TRAINING）

| # | 事项 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | VLM-001：红测试 `tests/platform/test_vlm_contracts.py` 13 项 RED（模块不存在）→ 实现 → 全绿 | 0 | 新建 `src/modules/fmcg/cascade/{__init__,contracts}.py`：Candidate/RegionRef/PredictionEnvelope/CandidateSet/RiskDecision/CascadePolicy/QwenSkuDecision 全部 extra=forbid+frozen；accepted 需 sku_id+evidence_ids；calibrated_risk∈[0,1]；stage 限 S1–S5；RiskDecision NaN/Inf/缺校准版本 fail-closed；QwenSkuDecision 冻结 qwen-sku-decision.v1，`assert_sku_within_candidates` 闭集守卫（候选外 sku 不得 accepted）；全量 **518 passed + 1 skipped**（基线 505+13） |
| 2 | VLM-002：红测试 `tests/platform/test_vlm_registry.py` 12 项 RED（manifest 不存在）→ 实现 → 全绿 | 0 | `src/platform/registry.py` CapabilitySpec 新增 resource_class/residency/meter_units（有默认值，旧 manifest 兼容）；`capabilities()` 返回新字段；新建 `src/modules/fmcg/adapters/__init__.py` 与 `src/modules/fmcg/cascade/manifest.py`（8 能力 ID 冻结：quality=cpu/hot、scene=warm、detect/fast_sku=hot、sam/retrieve=warm、qwen=cold+mlx_vlm+token 计量、human=hot）；`register_fmcg_cascade` adapter 缺失 fail-closed；组合根 `build.py` 增可选 `cascade_adapters` 注入（默认不注入，行为不变）；依赖方向守卫健在（platform 未 import src.modules）；全量 **530 passed + 1 skipped**（518+12） |
| 3 | VLM-003：红测试 `tests/platform/test_model_residency.py` 17 项 RED（模块不存在）→ 实现 → 全绿 | 0 | 新建 `src/platform/model_runtime.py` ModelResidencyManager：状态机 cold/loading/hot/unloading/failed；租约带 run_id/attempt_id/deadline；max_concurrency 并发控制（qwen3-vl:4b=1 sleeping guardian）；过期租约显式 reap（未 reap 仍占名额 fail-closed）；空闲超 idle_ttl_s 回落 cold（residency=hot 永不自动卸载）；加载失败→failed 熔断不重试；register/load/acquire/release/unload/reap 全写 audit；recover=True 恢复残留 loading；store.py 追加 migration 015（model_residency + model_lease，sha256 防篡改）；全量 **547 passed + 1 skipped**（530+17） |
| 4 | VLM-004：先写测试 `tests/platform/test_cascade_policy.py` 11 项（policy 模块不存在时为 RED）→ 实现 → 全绿 | 0 | 新建 `src/modules/fmcg/cascade/policy.py`：POLICY_VERSION=cascade-policy.v1；fast=S1/standard=S2/deep=S3/expert=S4（档位只限阶段上限，不代替内部 S 阶段语义）；require_quality_gate 恒 True；vlm_concurrency=1；queue_sla_hours 12/48 为队列业务 SLA，非推理 timeout；ResolvedPolicy（冻结 CascadePolicy+TierBudget max_regions/max_vlm_input_tokens）；policy_snapshot JSON 可序列化落 checkpoint；budget_exhausted_decision→budget_exhausted 路由；unknown_sku_decision→human；未知档位 PolicyNotFoundError fail-closed；全量 **558 passed + 1 skipped**（547+11） |
| 5 | VLM-005：先写测试 `tests/unit/test_cascade_risk.py` 14 项（risk 模块不存在时为 RED）→ 实现 → 全绿 | 0 | 新建 `src/modules/fmcg/cascade/risk.py`：decide_risk 只允许 calibrated_risk 路由，calibrator=None 抛 CalibrationUnavailable；硬冲突（ocr/attribute_conflicts）强制升级 S4，超档位 max_stage 或已在 S4 转人工；NaN/Inf/缺 top1→route=human；未识别 stage 抛 RiskComputationError；load_calibrator 冻结 JSON+SHA256 校验（篡改报 CalibratorTamperedError）；bootstrap_rule_v1 kind=bootstrap_rule 明确标注非概率校准；阶段阈值映射 S1→fast_accept_risk…S4→expert_accept_risk；全量 **572 passed + 1 skipped**（558+14） |
| 6 | VLM-006：先写测试 `tests/unit/test_cascade_adapters.py` 15 项 RED（适配器不存在）→ 实现 → 全绿 | 0 | `cascade_inference.py` 新增只读 `detect_regions()`（只出 region：region_id/box_px/宽高/detector 线索，不含 status/sku_id 决策字段）与 `classify_region()`（Top-K/margin/entropy/model_version）+ `model_versions()`；`recognize()` 逻辑逐行未动，旧 gate/SAM/8091 回归全绿；新建 5 适配器：legacy_cascade（异常→CapabilityAdapterError）、quality（四级词汇冻结，未知/异常→manual_review）、scene（无证据诚实 unknown，非法词汇 fail-closed）、sam_refiner（coarse/mask/context 三引用，10%–20% 外扩，mask 失败保留原框+needs_review 不伪造）、sku_retrieval（闭集过滤，registry 空/后端缺失 fail-closed）；`src/pipeline/recognize.py` 本轮无改动（计划列出但无需提取）；全量 **587 passed + 1 skipped**（572+15） |
| 7 | VLM-007：红测试 `tests/unit/test_qwen3vl_adapter.py` 15 项 RED（模块不存在）→ 实现 → 全绿 | 0 | 新建 `src/modules/fmcg/adapters/qwen3vl_mlx.py`：受控 base_url（仅 http/https，file:// 等拒绝）；固定 prompt 模板只注入 region/asset_sha/registry_version/候选 SKU，忽略 context 中 system_prompt 等注入键；输出经 QwenSkuDecision（qwen-sku-decision.v1）校验；映射 accepted→accepted（限闭集内）/unknown→unknown/same_sku_new_package+possible_new_sku→new_package/insufficient_evidence→needs_review；候选外 accepted→needs_review+sku_outside_candidate_set（红线）；非法 JSON→invalid_model_output、空响应→empty_response；registry_version 缺失/空候选 fail-closed 不发请求；429/503/Timeout/Connection 可重试（max_retries 注入）、其他 4xx 不重试，重试耗尽 QwenTransportError；调用前 acquire qwen3-vl:4b 租约（busy 直接 ModelBusy 不发请求）finally release；全 fake HTTP backend，不加载权重、不发起真实前向（BLOCKED_BY_ACTIVE_TRAINING）；全量 **602 passed + 1 skipped**（587+15） |
| 8 | VLM-008：红测试 32 项（quality_gate +7、split_guard 12、builder 13，模块不存在/新函数缺失）→ 实现 → 全绿 | 0 | `quality_gate.py` 新增 V2 处置：tilt_observed 不可观测返回 None；decide_quality：unobservable→manual_review（reason tilt_unobservable）、单一弱启发式→warn、≥2 维 fail 才 reject；assess_quality 三维打分；gate_decision/tilt_score V1 口径保留向后兼容；`run_quality_screen.py` 改 V2 处置（accept/accept_warn/manual_review/reject，解码失败→manual_review），旧 tilt reject 历史 JSON 不改写；新建 `src/training/vlm/`：contracts（VlmSample 冻结：SHA/宽高/box_px/bbox_1000/target_type/label_source/split_group/evidence，closed_set 需 sku_id）、split_guard（SHA/near_dup/customer/store/session/package_version 六维跨 split 重叠 + frozen/active_protocol 禁入 train，违规附清单）、builder（staging→磁盘核对→os.replace 原子发布；目录已存在 DatasetExistsError；review_status非train/label_source非human_final、gold_verified 无裁决不进 train，SAM 几何通过≠human_final；泄漏发布前阻断且清理 staging；四类样本直方图+同图重复视觉 token 审计）、hf_dataset（仅 images+messages 结构化 content，禁手工 vision token）；`scripts/build_qwen3vl_dataset.py` 入口 fail-closed；qpol_v2 历史不可变规则继续通过；全量 **634 passed + 1 skipped**（602+32） |
| 9 | VLM-009：红测试 `tests/unit/test_vlm_preflight.py` 11 项 RED（模块不存在）→ 实现 → 全绿 | 0 | 新建 `src/training/vlm/preflight.py`：REQUIRED_PROBES 12 维冻结；run_preflight 注入式探针（fake 测试）；G-CURRENT：进程表 src.training.train_v1/mlx_vlm.lora 或活跃训练租约→active_training_conflict（ok=false 不得继续）；G-APPLE：未获下载授权→download_authorization_required；探针缺失抛 PreflightError，探针崩溃 fail-closed；输出目录已存在→output_dir_exists；`scripts/run_qwen3vl_preflight.py` 真实入口：mlx 未安装时诚实 fail-closed（禁止假装已验证），证据写 .eval/vlm_preflight/<run_id>/ 不覆盖，swap 停止线 8192MB 入报告；pyproject 增 vlm-train 可选依赖声明（仅声明不安装，独立环境 .venv_mlx_vlm）；本轮未执行真实 preflight（BLOCKED：需下载授权+当前训练存在）；CLI --help parse-only 验证通过；全量 **645 passed + 1 skipped**（634+11） |
| 10 | VLM-010：先写测试 `tests/unit/test_vlm_evaluate.py` 17 项（evaluate/benchmark 模块不存在时为 RED，未单独执行红运行，同 VLM-004 如实记录）→ 实现 → 全绿 | 0 | 新建 `src/training/vlm/evaluate.py`：record 助手 + evaluate_records 确定性报告（coverage/accepted_precision/Top1/Top5/unknown/new_package P-R/schema_compliance/candidate_escape/attribute_accuracy/p50、p95 线性插值/tokens_per_second/逐实例 error_ledger）；零 coverage→accepted_precision=None+gate_pass=False（高 precision 不得掩盖零 coverage）；gate 需 coverage>0+precision≥阈+escape=0+schema 全合规；分母 0 一律 None；新建 `src/training/vlm/benchmark.py`：冻结矩阵 batch 1/2/4×low/high_tokens×qlora/bf16；run_benchmark 注入式 executor，每 probe 独立目录（已存在拒绝），实测字段（sample/region/token/wall）缺失抛 BenchmarkError，estimation_basis=measured 禁用照片数估时；`scripts/run_qwen3vl_zero_shot.py`、`run_qwen3vl_benchmark.py` 无 ok=true preflight 报告拒绝执行，benchmark 主环境诚实 blocked（mlx 未安装）；两 CLI --help parse-only 验证通过；真实 zero-shot/benchmark 未运行（BLOCKED：需 Task 9 真门通过）；全量 **662 passed + 1 skipped**（645+17） |
| 11 | VLM-011：红测试 `tests/platform/test_vlm_training_gov.py` 20 项 RED（模块/方法不存在）→ 实现 → 全绿（+1 CLI 共 21） | 0 | 新建 `src/training/vlm/train.py`：check_vlm_gates 证据链门禁不短路（snapshot/preflight/zero-shot/benchmark 缺失、输出目录占用、训练冲突、未授权、batch 超 benchmark、epochs/rank/alpha 超第一轮上限、instance 非 5,000–20,000、train_vision 未独立授权），VlmPlanError 携带全部 blocker；build_mlx_command 只生成 MLX-VLM 白名单参数（`--model-path/--dataset/--batch-size/--epochs/--learning-rate/--grad-checkpoint/--gradient-accumulation-steps/--train-on-completions/--lora-rank/--lora-alpha/--output-path`，独立授权后另附 `--train-vision`），禁 `--use-mps/--num-epochs`；业务名 qwen3-vl:4b、基础模型 mlx-community/Qwen3-VL-4B-Instruct-4bit、官方基线 Qwen/Qwen3-VL-4B-Instruct 固定，Ollama Q4_K_M 不得作训练输入；`training_gov/service.py` 增 plan_vlm_training（kind=dry_run+status=vlm_dry_run，不改 training_run CHECK 枚举；授权类 blocker→AuthorizationRequired，其余 TrainingGovError；入审计）、complete_vlm_training（adapter/config/loss/tokens_per_second/env_lock/data_hash/model_revision/error_ledger 八件缺一拒绝，仅产生 completed_candidate，publish_status 保持 none，发布仍需独立 admin 审批）、set_vlm_vision_authorized（独立 flag+IAM，不与 training_authorized 合并）；API 增 POST /api/v1/training/runs/vlm/plan（未登录拒绝、未授权 403、证据缺失 400）；`scripts/run_qwen3vl_lora.py` 无 ok=true preflight 拒绝（exit 2/3），通过后仅输出冻结命令并 blocked=true（exit 4），不加载权重不发起训练；回归 `tests/platform/test_m5_training_gov.py` 全绿；真实 QLoRA 未执行（BLOCKED_BY_ACTIVE_TRAINING）；全量 **683 passed + 1 skipped**（662+21） |
| 12 | VLM-012：红测试 `tests/platform/test_cascade_loop.py`（模块不存在 collection error RED）→ 实现 → 12 项全绿 | 0 | 新建 `cascade/graph.py`：GraphV2 fmcg_cascade_s0_s5，14 节点严格按规格（quality/scene/detect/classify_fast/risk_s1/segment/reclassify/risk_s2/retrieve/risk_s3/vlm_rerank/risk_s4/human_review/finalize），多条件边全部 when 标签由 router 决定，未匹配 edge 内核 fail-closed，本图无 feedback 边；新建 `cascade/service.py`：CascadeService 复用 LoopEngine（唯一 Orchestrator，无第二套任务系统），policy_for 快照随 run checkpoint 冻结；四条路由测试全绿：fast S0→S1 accepted（不进 VLM）、standard S1 高风险→S2 accepted、expert 硬冲突→S3→S4 Qwen 闭集裁决 accepted（Qwen 仅调用 1 次）、unknown→S5 waiting_human 后全新 service 实例同 store 跨进程恢复 accepted；预算耗尽（fast max_regions=8 vs 99 region）/VLM 不可用（QwenTransportError 熔断不无限重试）/SLA 过期（queue_deadline_at 已过→转人工并写审计）；idempotency_key 重提返回同一 run 且 billing 账本不重复（按 node#round 幂等键）；轨迹不只 route label：每节点 trail 含 policy_version/tier/risk/budget before-after/SLA/模型/证据 ID，不记录密钥与 prompt 客户数据；新建 `adapters/human_review.py`：S5 交接单与裁决登记（accepted 必须 sku+证据）；质量 manual_review 阻断入口不进识别；人工 reject 为终态 failed；回归 test_u5_loop_kernel/test_u5_real_loop 全绿；全 fake backend，不加载任何真实模型；全量 **695 passed + 1 skipped**（683+12） |
| 13 | VLM-013：红测试 `tests/platform/test_cascade_billing.py`（模块不存在 collection error RED）→ 实现 → 10 项全绿 | 0 | 追加式迁移 016：job 表重建扩展 status CHECK（新增 expired）并增 attempt_timeout_at/queue_deadline_at 双时间戳，旧数据 COALESCE 回填；新建 cascade_usage 账本表 UNIQUE(run_id,billing_key)；usage_event/graph_run/audit_event/evidence_bundle 历史表全部保留，不 drop/rename（重建仅内部临时表 job_m016→rename 回 job）；`jobs.py`：expired 终态入状态机，attempt_expired 与 queue_deadline_passed 语义分离（单次 VLM attempt 超时≠任务过期），expire_job_at_deadline 到期置 expired+审计 job.queue_deadline_expired，已终态/未到期 no-op；新建 `cascade/billing.py`：rate-card.v1 七能力积分价目+tier 乘数，bill_attempt 全字段留痕（capability/model/version/photos/regions/tokens/compute_ms/tier/cold_start/cache_hit/rate_card_version/resource_cost/billed_cost），run 不存在拒绝记账，相同 billing_key 重试不重复计费；迁移可重复执行（第二次打开库无错、旧 usage_event 保留）；回归 test_m6_worker/test_platform_store 全绿；真实训练未受影响，本任务零 MPS/GPU/网络动作；全量 **705 passed + 1 skipped**（695+10） |
| 14 | VLM-014：红测试 `tests/platform/test_cascade_api.py`（模块不存在 collection error RED）→ 实现 → 16 项全绿 | 0 | 新建 `src/platform/api/cascade.py`：7 端点（POST/GET tasks、详情/regions/trail/cancel、models/runtime）；pydantic extra=forbid 拒绝 file_path/model/prompt/graph 任意字段（422）；tier/source 白名单；URL SSRF 防护（http/https only，localhost/私网/链路本地/保留地址拒绝）；未登录 401，写端点 session+CSRF，身份只取服务端 session；Idempotency-Key 重放同一 RecognitionTask 不重跑级联；五入口（single_file/batch_file/url/api/agent）共用 recognition_task 台账 entry=cascade_<source>；取消写审计 cascade.task_cancelled；提交响应 production_switch=false（shadow 默认）；旧 /api/v1/recognition/recognize 与 8091 口径不变且零影响；app.py 增 cascade_router 参数与 bundle.cascade_service 自动装配；bundle.py PlatformBundle 增可选注入位；回归 test_u2_recognition_tasks/test_umt006_auth 全绿；全 fake backend；真实训练未受影响，零 MPS/网络动作；全量 **721 passed + 1 skipped**（705+16） |


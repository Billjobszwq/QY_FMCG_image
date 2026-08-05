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

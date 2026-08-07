# Project Logic Chain V3 · EXECUTION-LOG

追加式，不覆盖历史。

## 2026-08-07 基线与复现

- `git rev-parse --short HEAD` → 7b2e268；分支 feat/unified-workbench-training-readiness。
- `git status --porcelain` → 仅 4 个受保护未跟踪目录（.quality/.sam_checkpoints/.sam_runs/.superpowers/）。
- 服务探测：8092=200、8400=200、8300=302（LS 登录跳转）、8091 / 根路径 404、/health {"error":"not found"}。
- 训练进程扫描：无 YOLO/QLoRA/classifier/finetune 训练进程（仅 oMLX 应用与 8092 monitor）。
- pytest tests/ → **819 passed, 1 skipped**（21.33s，miniconda python3）。
- P0 复现脚本（python3 内联）：
  - diagnostic_v1.json：photo_ids 500 / sha256 500，两数组各自 sorted=True；
  - 按位置 zip 对照 clean_manifest 真值：2/500 正确；
  - review_queue_diag_v1.json：250 项（double_review 200 + blind_manual 50），
    ID/SHA 配对 0/250 正确，唯一照片 226。
- sqlite3 .platform/platform.sqlite：integrity_check=ok；schema_migrations 001–018；
  review_task_v1：rq_v1 blind_manual 50 + double_review 200；review_event_v1=1；gold_region_v1=0。
- 阅读：GLOBAL_AGENT_ROUTING.md、CODEX-PROJECT-HANDBOOK.md、platform-v2/STATUS.md、
  sam-reannotation/STATUS.md、protocol_sets.py、build_review_queue.py、human_review_queue.py、
  import_u4_review_queue.py、review.py、store.py。
- 建立本档案目录与实施计划（纯文档基线，随后提交）。

## 2026-08-07 S2–S5（commit 2/3/4）

- **Commit 2** `ea3d69b` test: reproduce diagnostic photo sha mismatch（tests/unit/test_protocol_photo_identity.py，9 条红测试）。
- **Commit 3** `78b567b` fix: build canonical protocol photo identity mapping
  - 新增 `src/data/photo_identity.py`：canonical_mapping/validate_pairing/validate_queue_items/canonical_assets；fail-closed，allow_partial_import 恒 False。
  - `src/data/protocol_sets.py` freeze/make_dev_v2 输出追加 `photo_sha256_map`（按 ID 查询生成）。
  - 9/9 绿；tests/unit 237 全绿。
- **S4 队列失效 + V2 发布（Commit 4 `fa8eec1`）** feat: invalidate rq_v1 and publish review queue v2
  - migration 019：`review_queue_ledger_v1` + `review_queue_invalidation_v1`（触发器禁删改，追加式不可变）；store 增 register/invalidate/list_queue_ledger/list_review_tasks_active/review_task_stats。
  - `src/review/review_queue_v2.py`：ID→SHA 一律按 photo_id 查 clean_manifest，禁位置 zip；发布门禁（映射/配对/blob 存在/现场 SHA）任一失败不发布。
  - 真实构建 `.review_queue/review_queue_diag_v2.json`：**500/500 映射、250/250 配对、226/226 原图、226/226 现场 SHA**，分布 double 200 + blind 50（seed=20260804），重叠 24。
  - 失效驱动：sqlite backup API 备份 + 双向 integrity_check=ok → register rq_v1/rq_v2 → invalidate rq_v1（reason=invalid_id_sha_mapping，superseded_by=rq_v2）→ 证据 `.review_queue/rq_v1_invalidation_evidence.json`。
  - U5 导入：导入前 validate_queue_items 250/250 → imported=250，幂等重跑=0；task_stats active=250 / invalid=250 / total=500。
  - 全量测试 845 passed（基线 819 + 新增 26）。

## 2026-08-07 S6–S7（commit 5/6/7）

- **Commit 5a** `a5d82c7` test: require database as single review status source（8 条红测试）。
- **Commit 5** `a6bc48a` fix: use database review state as single source
  - `review.py` 新增 `review_progress(store)`：状态完全由 review_task_v1 + review_event_v1 + 队列账本推导；active/invalid 分开统计。
  - `workitems.py` 删除 `_load_review_queue` 静态 JSON 读取，WorkItems 走同一 DB 推导服务；`pending_review` 只计 status=pending。
  - `vocabulary.py` 增加 claimed/awaiting_second/awaiting_arbitration/finalized。
  - 3 个旧 U2 测试迁移为 DB 种子（JSON env 保留作为"被忽略"证据）。
- **Commit 6** `5468423` test: define region-level double review contracts（19 条，15 红）。
- **Commit 7** `5537af5` fix: make gold submission atomic and geometry-aware
  - 原子提交：`_prepare_region` 全量校验 + `store.add_gold_regions_atomic`（BEGIN/COMMIT，失败整批 ROLLBACK，review 事件也不落）。
  - bbox：x1/y1=0 合法；拒长度≠4/非数字/负坐标/x2<=x1/y2<=y1；width/height 可选越界校验。
  - 双审 one-to-one IoU 匹配（DOUBLE_REVIEW_IOU_THRESHOLD=0.75，降序贪心），匹配对再比 SKU；未匹配=分歧。
  - 仲裁只覆盖 IoU 匹配的分歧组；未分歧区域保持 human_final；仲裁逐区域 gold_verified。
  - 全量 871 passed, 1 skipped（基线 852 + 新增 19，零回归、零旧测试迁移）。

## 2026-08-07 S8（commit 8a/8）

- **Commit 8a** `6917e95` test: define ls v2 payload contracts（8 条红测试）。
- **Commit 8** `d306e44` feat: connect v2 queue to usable Label Studio workflow
  - `src/review/ls_v2_payload.py`：纯构建 payload；blind 序列化文本零 predictions/model_version/score/suggested（盲审零模型信息）；blob 缺失 fail-closed；重叠照片标记 overlap_photo_ids（assisted/blind 身份隔离）。
  - 真实接入：新建 LS 项目 **19 diag_v2_assisted（200 任务）** 与 **20 diag_v2_blind（50 任务）**；multipart 逐张上传 250/250（226 唯一+24 重叠双传）；meta 回填 task_ref/photo_id/sha256。
  - 守护：项目 1/10~13 创建前后两次校验标题逐字未变；LS 未重启；图片抽查 GET 200。
  - 证据：`.review_queue/ls_v2_evidence.json`。人工入口 http://127.0.0.1:8300/projects/19 与 /projects/20。
  - 全量 879 passed（基线 871 + 8）。
  - 未决：assisted predictions 为空（队列侧无 proposals，按契约不伪造；可后续经 predictions API 追加）。

## 2026-08-07 S9（commit 9a/9）

- **Commit 9a** `84512b2` test: define truebox gold export contracts（10 条红测试）。
- **Commit 9** `6a04bc8` feat: export immutable diagnostic truebox gold
  - `src/review/truebox_export.py`：build_truebox_export/export_truebox_gold/load_truebox_v2/gt_images_from_export；严格模式 fail-closed（submitted/conflict/失效队列/sha 不一致即拒绝）；只允许 human_final/gold_verified；原子写+拒绝覆盖；0 gold 不写文件。
  - 全字段审计：export_hash/protocol_hash/git_commit/source_queue_versions/reviewer 链/evidence_ids/store-session-近重复组。
  - `scripts/run_truebox_eval.py` load_gt 兼容 v1/v2；`scripts/export_truebox_v2.py` 生产库干跑：0 gold 未写文件（gold_region_v1=0）。
  - 全量 889 passed（879 + 10）。

## 2026-08-07 S10–S11（commit 10/11/12a）

- **Commit 10a** `21fd488` test: require canonical sku identity in zero-shot eval（13 条红测试）。
- **Commit 10** `ca95e79` fix: evaluate sku identity by canonical id
  - `src/training/vlm/evaluate.py`：SkuIdentityIndex/resolve_sku_identity/classify_sku_identity；dataset_class→canonical_sku_id→package_version_id→KB vector_id 链；评估禁展示名比较。
  - 7 类错误分类：true_kb_missing/alias_mapping_missing/package_version_mismatch/retrieval_miss/reranker_miss/registry_escape/unknown-new_packaging。
  - 旧 report 只读重放：accepted_precision 0→0.125，recall@1 0→0.5，registry_escape 22→0；真实短板 alias_mapping_missing 20（KB 缺碳酸/果汁参考图，需业务补图）。
- **Commit 11** `d89fc82` test: verify end-to-end review chain（9 条端到端链测试：构建→导入→状态机→gold→失效隔离→truebox→WorkItems 一致）。
- **Commit 12a** `4a84172` feat: prepare 5+5 acceptance batch awaiting human
  - `.review_queue/acceptance_batch_5plus5.json`/`.md`：5 assisted + 5 blind（含 2 组同图对照 35996301/36013437），全部来自真实 V2 队列；status=AWAITING_HUMAN_ACCEPTANCE；15 项自检清单。
  - 一致性：平台库 active=250 == 队列 250 == LS 19+20 任务 250。
  - 全量 911 passed（902 + 9）。

## 2026-08-07 S12b（收尾复核：发现并修复 API/批次门禁断链残余）

- 现场复核发现两处§八断链残余（旧代码/旧口径未覆盖 API 与批次门禁）：
  1. `/api/v1/review/status` 直接 `list_review_tasks()`（全部 500，含失效 rq_v1）；
  2. `batch_report` 同样统计全部任务 → 失效 V1 的 pending 将在 V2 完成后永久阻断阶梯推进。
  另发现运行中的 8400 进程（pid 31270，周三启动）仍是统一状态源合入前的旧代码。
- 红测试先行：
  - tests/platform/test_review_status_source.py +2（status 默认只 active；tasks-active/tasks-history 分离）；
  - tests/platform/test_u4_batches.py +1（失效队列不阻断批次门禁：complete/ready 判定只计 active）。
- 修复：
  - `src/platform/api/review.py`：status 走 review_progress（active/invalid 分开）；
    新增只读 `/api/v1/review/tasks-active`（默认列表）与 `/api/v1/review/tasks-history`（历史/失效证据，逐条 invalidated 标记）。
  - `src/platform/annotate/batches.py`：batch_report 改 `list_review_tasks_active()`。
- 8400 graceful 重启（kill -TERM 旧进程 → nohup src.composition.serve --port 8400，日志 /tmp/platform_8400.log）。
- 真实 API 对账（重启后）：review/status n_tasks=250（rq_v2 pending 250，invalid=250 rq_v1）；
  tasks-active=250 全 rq_v2；tasks-history=250 全 rq_v1 且 invalidated=True；
  workitems pending_review=250；与 DB review_task_v1（active=250/invalid=250）一致。
- 全量测试 **914 passed, 1 skipped**（911 + 3 新增，零回归）。
- 其余收尾复核证据：全量 pytest 前 911 passed；web tsc --noEmit 干净 + vite build 成功；
  sqlite integrity_check=ok、19 migrations、gold_region_v1=0；
  rq_v2 现场重验 pairing 250/250、唯一照片 226；LS 项目 19(200)/20(50) 在位、blind 抽样 5/5 零泄漏；
  8091 bundle=prod_20260805_v5_r1 未切换；8092/8400/8300 健康；无训练进程。

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

# 2026-08-07 项目逻辑链梳理与 Gold Review V2 实施计划

> 主实施 Agent 计划文件。范围：修复 diagnostic_v1 / 250 条审核队列 / Label Studio /
> 区域金标准 / truebox 评估 / 训练治理之间的断链；统一事实源与正式入口；
> 不启动任何重训练，不切换生产 bundle。
>
> 执行档案：`docs/implementation/project-logic-chain-v3/`
> 基线：HEAD `7b2e268`，分支 `feat/unified-workbench-training-readiness`，
> 测试 819 passed / 1 skipped（2026-08-07 现场重验）。

## 0. 绝对红线（摘自任务书，任何阶段不得越过）

1. 不删除/覆盖任何历史文件、SQLite、队列、模型、数据集、日志、截图、报告、失败产物、备份。
2. 不 git reset --hard / force push / merge / rebase / 部署。
3. 不改写不可变协议与不可变审核记录（触发器保护表禁止 UPDATE/DELETE）。
4. 不触碰 `.quality/` `.sam_checkpoints/` `.sam_runs/` `.superpowers/`。
5. 8091/8092/8400（及 8300 Label Studio）服务不中断；生产 bundle 不自动切换。
6. diagnostic/gold/calibration/dev 冻结协议集不进训练；prediction/SAM proposal/模型建议/测试 annotation 不得冒充 human_final。
7. 不为门禁通过降低既定标准；历史错误数据保留，追加式 invalidation/supersession 失效。
8. 真实人工审核到来前停止并标记 AWAITING_HUMAN_ACCEPTANCE，不伪造 human_final。

## 1. P0 根因与现场复现（2026-08-07 已复现）

- `src/data/protocol_sets.py` L230-231：协议写 `"photo_ids": sorted(ids)` 与
  `"sha256": sorted(...)` 两个**独立排序**数组。
- `scripts/build_review_queue.py` L28-29：按数组位置 `zip(photo_ids, sha256)` 配对。
- 现场核验：协议 zip 配对 2/500 正确；`.review_queue/review_queue_diag_v1.json`
  250 条 ID/SHA 配对 0/250；226 张唯一照片；double_review 200 + blind_manual 50。
- 权威映射源：`.batch3_clean/clean_manifest.json`（photo_id → sha256/width/height/filename）。
- 当前 gold_region_v1 为 0 行 → 人工真值尚未被污染（可安全失效 V1 队列）。
- DB 现状：review_task_v1 有 rq_v1 任务 250 条（200 double + 50 blind），
  review_event_v1 有 1 条（1 claim），gold_region_v1 = 0。integrity_check = ok。

## 2. 实施序列（小提交链，TDD 红测试先行）

### S1 docs: baseline current end-to-end logic chain
- 新建 `docs/implementation/project-logic-chain-v3/`：STATUS / IMPLEMENTATION-LIST /
  DECISIONS / ISSUES / EXECUTION-LOG / ACCEPTANCE / CURRENT-LOGIC-CHAIN /
  SOURCE-OF-TRUTH / MIGRATION-AND-COMPATIBILITY。
- 纯文档提交，不含代码。

### S2 test: reproduce diagnostic photo sha mismatch（红测试）
新文件 `tests/unit/test_protocol_photo_identity.py`：
1. 独立排序的 photo_ids/sha256 按位置 zip 必须被检测为错配（红）。
2. canonical mapping 必须能按 photo_id 从权威 manifest 查到 sha256（红）。
3. 队列导入前逐条 `actual_sha(photo_id) == declared_sha256`，错一条 fail-closed（红）。
4. 同 SHA 不同 photo_id → canonical asset 规则 + 别名证据保留（红）。
5. 队列文件已存在拒绝覆盖、必须发新版本（现有 write_queue 已有，补测试）。

### S3 fix: build canonical protocol photo identity mapping
- 新增 `src/data/photo_identity.py`：
  - `canonical_mapping(photo_ids) -> {photo_id: sha256}`（从 clean_manifest 按 ID 查询）；
  - `validate_pairing(pairs) -> report`（fail-closed）；
  - 处理同 SHA 多 photo_id（canonical asset + alias 证据）。
- `protocol_sets.py`：冻结输出增加 `photo_sha256_map`（映射本体），
  保留 `photo_ids`/`sha256` 数组仅为兼容；`dev_v2` 同理。
  **不修改已冻结的 diagnostic_v1.json**（只读 0444，不可变协议）。
- `scripts/build_review_queue.py`：保留不动（v1 历史构建器）；v2 构建器走 canonical mapping。

### S4 feat: invalidate rq_v1 and publish review queue v2
- `PlatformStore` 新增 migration 019：
  - `review_queue_ledger_v1`（队列版本账本：version/status/root_cause/
    discovered_at/impact/git_commit/evidence_path/superseded_by，追加式不可变）；
  - `review_task_invalidation_v1`（追加式失效记录，不改 review_task_v1 行）。
- 迁移前 sqlite3 backup API 备份 + integrity_check（store.backup 已存在，驱动脚本调用）。
- rq_v1 标记 `invalid_id_sha_mapping`；1 条 claim 保留但不计入活动进度。
- 生成 `.review_queue/review_queue_diag_v2.json`（queue_version=rq_v2）：
  - 前 200 个照片 ID 进 assisted/double（保留原设计）；
  - seed=20260804 从 500 ID 盲抽 50 blind；保留 24 张同图对照；
  - 250 任务 / 226 唯一照片；SHA 全部按 photo_id 从 manifest 查询。
- 构建审计 JSON（builder version/hash、git commit、protocol hash、manifest hash、
  seed、mapping hash、250 任务 hash、226 唯一、24 重叠、现场 SHA 核验、
  assisted/blind 分布、零错误、supersedes rq_v1）。
- 发布门禁：500/500 映射可恢复、250/250 正确、226/226 文件存在、
  226/226 现场 SHA 一致、证据完整；任一失败不发布。
- 导入脚本 `scripts/import_u5_review_queue_v2.py`：导入前逐条校验（fail-closed），
  幂等，queue_version=rq_v2。

### S5 fix: use database review state as single source
- 新增 `src/platform/annotate/review_state.py`：统一状态查询服务
  （review_task_v1 + review_event_v1 + active queue version），
  active/invalid/superseded 分开统计；失效 V1 不阻断 V2。
- WorkItems / Overview / Assets / 审核详情 / 批次门禁全部改走该服务；
  JSON 队列只作不可变导入制品，不再作为运行状态源。

### S6 test+fix: region-level double review contracts（gold_region 状态机）
红测试覆盖 → 修复 `src/platform/annotate/review.py`：
1. 原子提交：一次提交的 review event + 全部 regions 同一事务；任一失败整次零落账；
   重试幂等；事务失败有证据（migration 020 加 gold_region_submission_v1 提交组表）。
2. 合法 bbox：x1/y1 允许 0；校验 x1>=0, y1>=0, x2>x1, y2>y1, x2<=width, y2<=height，
   有限数；保存图像宽高与坐标系版本（migration 020 给 gold_region_v1 追加列）。
3. 双审一致性：禁止只比 region_id+sku_id+sku_name；one-to-one 几何匹配
   （版本化 IoU 阈值写入协议与证据）+ canonical sku_id 比较；
   漏框/多框/重复框/SKU 不一致进 conflict。
4. 区域级仲裁：按 conflict group/region pair 仲裁；未分歧区域不被覆盖；
   逐区域 gold_verified；原提交保留 superseded 证据；不重复计数。
5. 身份隔离：actor 来自登录 session；同一 actor 不得一审+二审；
   assisted/blind 同图任务不得同一 actor；arbiter 需仲裁权限；
   blind payload/API/网络响应不含 prediction。

### S7 feat: connect v2 queue to usable Label Studio workflow
- 新建 LS V2 项目（不动项目 10~13，不删除不覆盖）。
- payload 构建器从 rq_v2 + blob 原图 + SAM proposal（assisted）构建；
  blind 任务零 prediction 字段。
- `.sam_runs/ls_import_20260804_195327/ls_payload.json`（9 张，与 226 交集 0）
  不得冒充 V2 payload（登记进 ISSUES 证据）。
- 前端 `web/src/pages/Assets.tsx` + `web/src/api.ts`：跳转 LS 任务或原生多区域画布；
  regions 完整提交；SKU canonical identity；assisted/blind 标识；进度/二审/分歧/
  仲裁/gold summary/证据链。统一管理页不得再把"手输一个坐标框"描述为完整审核。
- 5+5 小规模验收批（≥2 张同图对照）先行，机器侧 15 项检查通过后
  状态 = AWAITING_HUMAN_ACCEPTANCE。

### S8 feat: export immutable diagnostic truebox gold
- 新增 `src/eval/truebox_export.py`：gold_region_v1 →
  `.data_protocol/diagnostic_v1_truebox_v2/`（不可变版本化路径）；
  只允许 human_final + gold_verified；拒绝 prediction/unreviewed/submitted/
  conflict/superseded/invalid queue/model_provisional；
  输出全字段（photo/sha/uri/w/h/boxes/canonical sku/package_version/label_source/
  reviewers/evidence/store/session/near-dup/queue version/export hash/protocol hash/git commit）。
- `scripts/run_truebox_eval.py` 直接读正式导出格式，禁止人工中间 JSON。
- 不修改原 diagnostic_v1.json。

### S9 fix: evaluate sku identity by canonical id
- `scripts/run_qwen3vl_zero_shot_v2_infer.py` / `src/training/vlm/evaluate.py`：
  建立 dataset_class → canonical_sku_id → package_version_id → KB vector_id 映射；
  评估禁止比较展示名字符串。
- 报告拆分：true_kb_missing / alias_mapping_missing / package_version_mismatch /
  retrieval_miss / reranker_miss / registry_escape / unknown/new_packaging。
- 本轮只做代码/TDD/结构验证；不启动 Qwen 重推理或 QLoRA；真实 zero-shot 重跑等人工 gold + 单独授权。

### S10 test: verify end-to-end review chain + docs: finalize
- 全量 pytest、web build、TS 检查、SQLite integrity_check、API 对账、浏览器 QA、
  8091/8092/8400/8300 健康检查、git diff/status、生产 bundle 对账。
- CURRENT-LOGIC-CHAIN.md（22 层 Mermaid 全链）与 SOURCE-OF-TRUTH.md（17 类实体）定稿。
- 最终报告按任务书 §二十 23 项结构输出。

## 3. 测试矩阵（任务书 §十八 22 项 → 映射）

| # | 覆盖点 | 测试文件（新增） |
|---|---|---|
| 1 | protocol ID/SHA mapping | test_protocol_photo_identity.py |
| 2 | V1 invalidation | tests/platform/test_queue_invalidation.py |
| 3 | V2 active queue | 同上 |
| 4 | WorkItem 状态源一致 | tests/platform/test_review_state_source.py |
| 5 | 失效任务不进默认列表 | 同上 |
| 6 | assisted/blind 同图隔离 | tests/platform/test_review_isolation.py |
| 7 | blind payload 无 prediction | 同上 + test_ls_payload_v2.py |
| 8 | 多区域提交 | tests/platform/test_gold_regions_v2.py |
| 9 | 原子事务回滚 | 同上 |
| 10 | x1/y1=0 合法 | 同上 |
| 11 | box 越界拒绝 | 同上 |
| 12 | 双审 one-to-one IoU 匹配 | 同上 |
| 13 | 漏框/重复框/SKU 分歧 | 同上 |
| 14 | 区域级仲裁 | 同上 |
| 15 | gold export | tests/unit/test_truebox_export.py |
| 16 | diagnostic 冻结集禁止训练 | tests/unit/test_protocol_guard（已有补强） |
| 17 | raw SKU name 不参与 identity | tests/unit/test_sku_identity_eval.py |
| 18 | alias/package mapping | 同上 |
| 19 | LS payload round-trip | tests/platform/test_ls_payload_v2.py |
| 20 | 真实浏览器流程 | 浏览器 QA 证据（ACCEPTANCE.md） |
| 21 | 旧项目/旧制品零覆盖 | 验收检查清单 |
| 22 | 无训练、无生产切换 | 最终报告声明 + 进程证据 |

## 4. 提交纪律

- 只暂存本任务相关文件；不暂存四个受保护未跟踪目录；每次提交前跑对应测试；
  EXECUTION-LOG.md 记录命令/结果/证据路径。
- 提交链见 §2 S1–S10。

## 5. 暂停条件（出现即停止询问）

需要真实人工审核 / 删除历史制品 / 切换生产模型 / 启动重训练 /
新破坏性权限 / 无法从代码和事实判断的业务选择。

# Project Logic Chain V3 · IMPLEMENTATION-LIST

状态语义：OPEN / IN_PROGRESS / DONE / BLOCKED。每项含 ID/问题/当前事实/目标状态/
前置依赖/涉及文件/红测试/验收证据/状态/commit/阻断原因。

## PLC3-001 协议 ID/SHA 按位置 zip 错配（P0）
- 问题：diagnostic_v1.json 的 photo_ids 与 sha256 各自独立排序，消费方按位置 zip → 2/500 正确。
- 当前事实：2026-08-07 现场复现；rq_v1 队列 0/250 配对正确；gold_region=0 未污染真值。
- 目标状态：canonical photo_id→sha256 映射成为唯一配对途径；位置 zip 有红测试拦截。
- 前置依赖：无。
- 涉及文件：src/data/protocol_sets.py、scripts/build_review_queue.py、新增 src/data/photo_identity.py。
- 红测试：tests/unit/test_protocol_photo_identity.py（5 条）。
- 验收证据：500/500 映射恢复正确；250/250 队列配对正确。
- 状态：IN_PROGRESS；commit：—；阻断原因：无。

## PLC3-002 rq_v1 追加式失效
- 问题：错误队列已导入 review_task_v1（250 条）且有 1 claim，不可变表不能改行。
- 当前事实：review_task_v1 250 条 rq_v1；1 条 claim 事件；0 gold_region。
- 目标状态：队列版本账本 + 失效记录追加落账；rq_v1=invalid_id_sha_mapping；
  API/WorkItem/工作台默认只显示 active queue；1 claim 保留不计活动进度。
- 前置依赖：PLC3-001。
- 涉及文件：src/platform/data/store.py（migration 019/020）、scripts/invalidate_rq_v1.py（新增）。
- 红测试：tests/platform/test_queue_invalidation.py。
- 验收证据：备份（sqlite backup API）+ integrity_check + 账本行 + API 默认列表无 rq_v1。
- 状态：OPEN；commit：—。

## PLC3-003 发布 review_queue_diag_v2
- 问题：需要正确映射的 250 条队列（226 唯一照片，24 同图对照，double 200 + blind 50）。
- 当前事实：权威源 clean_manifest.json 完整；226 张原图存在于 .batch3_clean/blobs。
- 目标状态：rq_v2 发布 + 完整构建审计 + 发布门禁全过 + 导入 DB（导入前逐条校验 fail-closed）。
- 前置依赖：PLC3-001、PLC3-002。
- 涉及文件：scripts/build_review_queue_v2.py（新增）、scripts/import_u5_review_queue_v2.py（新增）。
- 红测试：导入校验 fail-closed 测试（PLC3-001 测试文件内）。
- 验收证据：构建审计 JSON；250/250、226/226 现场 SHA 核验；supersedes rq_v1。
- 状态：OPEN；commit：—。

## PLC3-004 统一审核状态源
- 问题：WorkItem 从静态 JSON 读 pending（曾显示 250 pending），审核 API 从 DB 事件推导（249+1 claimed）。
- 当前事实：两套状态源并存。
- 目标状态：review_task_v1 + review_event_v1 + active queue version 为唯一事实源；
  WorkItems/Overview/Assets/审核详情/批次门禁同一查询服务；总数/分页/筛选/导出一致；
  active/invalid/superseded 分开统计；失效 V1 不阻断 V2。
- 前置依赖：PLC3-002、PLC3-003。
- 涉及文件：新增 src/platform/annotate/review_state.py；web API 路由改接。
- 红测试：tests/platform/test_review_state_source.py。
- 验收证据：API 对账脚本输出一致；浏览器 QA。
- 状态：OPEN；commit：—。

## PLC3-005 gold_region 状态机修复
- 问题：①每 region 单独 commit 可能半次审核；②box 校验拒绝 x1/y1=0 且无上界/宽高；
  ③双审只比 region_id+sku_id+sku_name；④一个 arbiter region 可 supersede 整任务；
  ⑤身份隔离不完整。
- 当前事实：review.py 现状逐条对应任务书 §十一 1–5（代码已复核）。
- 目标状态：原子事务提交；bbox 全约束 + 图像宽高/坐标系版本；one-to-one IoU 双审匹配；
  区域级仲裁；session actor + 同图隔离 + blind 零 prediction。
- 前置依赖：PLC3-003（需要正确队列任务）；migration 020（gold_region_v1 加列）。
- 涉及文件：src/platform/annotate/review.py、src/platform/data/store.py。
- 红测试：tests/platform/test_gold_regions_v2.py（原子性/回滚/边界/匹配/仲裁/隔离）。
- 验收证据：全部红测试转绿 + 事务失败证据落账。
- 状态：OPEN；commit：—。

## PLC3-006 V2 接入 Label Studio + 前端 regions 提交
- 问题：统一 Web 只显示 photo_id + 手输坐标，不是真实标注系统；多套并行实现未收敛。
- 当前事实：LS 8300 运行中（项目 10~13 存在）；旧 ls_payload 9 张与 226 交集 0。
- 目标状态：LS V2 新项目（不动 10~13）；assisted 显 proposal、blind 零 prediction；
  多区域增删改 + canonical sku + unknown/new_packaging；前端跳转 LS 或原生画布完整提交 regions。
- 前置依赖：PLC3-003、PLC3-005。
- 涉及文件：src/ls_platform/（新 payload builder）、web/src/pages/Assets.tsx、web/src/api.ts。
- 红测试：tests/platform/test_ls_payload_v2.py（round-trip + blind 无 prediction）。
- 验收证据：5+5 验收批机器侧 15 项检查。
- 状态：OPEN；commit：—。

## PLC3-007 truebox 正式导出器
- 问题：缺 gold_region_v1 → diagnostic_v1_truebox_v1 → run_truebox_eval.py 正式出口。
- 当前事实：无导出器；评估曾依赖人工中间 JSON。
- 目标状态：不可变版本化导出（diagnostic_v1_truebox_v2/），仅 human_final+gold_verified，
  全字段 + hash + git commit；run_truebox_eval 直接读正式格式。
- 前置依赖：PLC3-005。
- 涉及文件：新增 src/eval/truebox_export.py、scripts/run_truebox_eval.py 适配。
- 红测试：tests/unit/test_truebox_export.py。
- 验收证据：导出 hash、禁入状态全部拒绝的测试。
- 状态：OPEN；commit：—。

## PLC3-008 zero-shot canonical identity
- 问题：GT「1250ml茉莉乌龙（无糖）」vs KB「茉莉乌龙无糖PET1250ML」被计为 registry escape。
- 当前事实：run_qwen3vl_zero_shot_v2_infer.py / vlm/evaluate.py 比较展示名字符串。
- 目标状态：dataset_class → canonical_sku_id → package_version_id → KB vector_id 链；
  报告拆分 7 类原因；KB 扩展前先修身份映射；旧 KB 版本不覆盖。
- 前置依赖：无（与审核链并行）。
- 涉及文件：scripts/run_qwen3vl_zero_shot_v2_infer.py、src/training/vlm/evaluate.py、Registry/KB builder。
- 红测试：tests/unit/test_sku_identity_eval.py。
- 验收证据：同义名称不再计 escape 的单测；报告字段齐全。
- 状态：OPEN；commit：—。

## PLC3-009 逻辑链与事实源文档定稿
- 问题：多套并行实现与多套状态，缺统一逻辑链与唯一事实源清单。
- 目标状态：CURRENT-LOGIC-CHAIN.md（22 层 + Mermaid）、SOURCE-OF-TRUTH.md（17 类实体）定稿。
- 前置依赖：PLC3-001~008 的事实。
- 状态：IN_PROGRESS（初版随文档基线提交，实施中持续更新）。

## PLC3-010 5+5 小规模验收批
- 问题：不得直接放行 250 条人工审核。
- 目标状态：5 assisted + 5 blind + ≥2 同图对照，机器侧 15 项检查通过 →
  AWAITING_HUMAN_ACCEPTANCE + 10 条真实访问链接。
- 前置依赖：PLC3-003~006。
- 状态：OPEN。

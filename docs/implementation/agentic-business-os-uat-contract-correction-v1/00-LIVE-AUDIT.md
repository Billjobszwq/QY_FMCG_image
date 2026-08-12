# 00 · 现场审计（UAT Contract Correction v1）

审计时间：2026-08-12。全部为实时核验，不依赖旧报告。

## Git / 服务 / 制品

- HEAD：`e45af4eb`（与任务书预期一致，无需 reset）；branch
  `feat/nextgen-training-cycle-v2`；单 worktree；tracked 干净。
- 服务：8091/8092/8300/8400 全 UP（abos status）；无训练进程。
- production：`prod_v4_best_r1`；`CURRENT.previous.json` 指向
  `prod_20260805_v5_r1`（回滚路径在位）。
- Detector：`best/sku_v4_best.pt` sha256 `84bf9936…5554975`
  （133,135,871 B）；Classifier：既有 ResNet18
  （sha256 `8a7a7f4c…`，与 v5 bundle 同 SHA）。

## DB

- `PRAGMA integrity_check=ok`；118 表；迁移至 `046_bi_dashboard_v1`。
- `work_item_v2`=13；`business_run_v1`=12；`workflow_definition_v1`=7；
  `survey_definition_v1`=14；`bi_dashboard_v1`=2；`import_batch_v1`=10；
  `agent_run_v1`=12。

## 已确认的契约断点（现场证据）

1. **agent_call Usage 无链**：12/12 条 `unit='agent_call'` 的
   `run_id`/`work_id` 均为空字符串，仅 `source_evidence=agent_run:*`。
   财务页无法下钻到 run/evidence。
2. **V4 shadow 报告 sku_name 全 `?`**：
   `.eval/shadow_v4_best_report.json` 中检出产品名全为 `'?'`——
   `recognition_shadow_compare.py` 读 `name` 键，识别器实际返回
   `sku_name`。旧报告"v4 检出 2/3 件"数量属实，但 SKU 身份未记录；
   且无 detector/classifier/registry/threshold hash、无负样本、
   无延迟分位数。
3. **门头必拍可绕过**：`survey.py submit` 只在 `min_count>0` 时计数
   media，无 `capture_role` 概念；`require_storefront=true` +
   `min_count=0` 即可无门头照提交（UAT 预演正是这样通过的）。
4. **Workflow parallel 是串行扇出**：`workflow.py` parallel 节点仅把
   后继放入 frontier 顺序执行；无分支身份/独立 ctx/并发/租约。
5. **rate limit 未实现**：登录/Agent/导入/识别均无限流（旧轮把它
   降级为 P2，本轮必须真实实现）。
6. **UAT 预演缺陷**：`scripts/v3_uat_rehearsal.py` 复用固定 fixture，
   客户/项目二次运行为 `skipped`；报告未包含手册规定的全部 ID
   （角色矩阵/截图/p50/p95/重启恢复等）；问卷以 `min_count=0`
   无门头照提交通过。

## T0 红测试结果（先 RED）

`tests/platform/test_uatcc_red_contracts.py`：10 failed + 1 passed：

| # | 测试 | RED 证据 |
|---|---|---|
| 1 | require_storefront 无照片提交 | 提交成功（应失败） |
| 2 | 无 storefront 角色照片 | attach_media 无 capture_role（TypeError） |
| 3 | 被跳题隐藏门头题不阻断（守卫） | **passed**（防过度修复） |
| 4 | Agent Usage 链路 | `run_id=''` |
| 5 | parallel wall-time | run failed（分支执行破损），更谈不上并行 |
| 6 | UAT 报告缺 ID 校验 | 模块不存在（ModuleNotFoundError） |
| 7 | inserted=0 判定 | 同上 |
| 8 | shadow 读 sku_name | `extract_products` 不存在 |
| 9 | 登录限流 | 15 次未 429 |
| 10 | Gate evaluator | 模块不存在 |

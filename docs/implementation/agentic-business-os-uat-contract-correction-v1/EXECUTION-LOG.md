# EXECUTION LOG（追加式）

## 2026-08-12 · T0 现场复核与红测试

- 阅读完成：GLOBAL_AGENT_ROUTING、CODEX-HANDBOOK、USER-HANDBOOK、
  OPERATOR-RUNBOOK、MODULE-AGENT-DEV-GUIDE、V3 目录全部（04/05/ISSUES/
  STATUS/EXECUTION-LOG 重点）、survey/workflow/runtime/usage_api/
  rehearsal/shadow 实现、近 30 commits、DB schema/迁移/服务/CURRENT/制品 hash。
- 现场：HEAD e45af4eb 与预期一致；四服务 UP；prod_v4_best_r1；
  detector sha 84bf9936…；integrity ok；118 表；迁移 046。
- 断点核验：agent_call 12/12 无 run_id；shadow products 全 '?'；
  门头 min_count=0 绕过；parallel 串行扇出；rate limit 缺失。
- 红测试：tests/platform/test_uatcc_red_contracts.py 10 failed + 1 守卫绿。

## 2026-08-12 · T1 照片契约（bd56676e）

- 迁移 047：survey_media_v1 +capture_role/status；usage_attribution_v1；
  workflow_branch_v1；rate_limit_v1/rule 表。
- survey.py：CAPTURE_ROLES；lint（require_storefront 不得绕过、
  required+min_count=0 冲突、role 非法、max<min）；submit 可见题
  照片校验（storefront/min/max，错误指明题目）；attach_media
  capture_role 校验+fail-fast；delete_media 软删除；模板新增
  q_storefront_photo。survey_api：capture_role 字段 + DELETE media。
- UI：Builder 照片检查器（角色/张数/profile/人工确认）；填写页
  角色下拉+门头提示+suggestion/final 分离。
- RED-1/2/3 → GREEN；v2 survey 旧测试适配（上传 storefront）。

## 2026-08-12 · T2 Agent 统一链（e0a478d3）

- runtime.invoke 重写：BusinessRun(agent.invoke)+WorkItem+Evidence
  （cas_hash=trace sha256）+挂链 Usage；失败同写；账本 fail-closed；
  parent/correlation/customer/project 继承，缺失显式 unattributed。
- 迁移 048：agent_run_v1 +business_run_id/evidence_bundle_id。
- workflow agent 节点传 parent_run_id/correlation/customer/project。
- usage_api：rows lineage 标记；reconcile-legacy/legacy 追加式账本；
  UsageWorkbench 历史未归属徽章+对账按钮。RED-4 → GREEN。

## 2026-08-12 · T3 真实并行（1de259aa）

- _exec_parallel/_exec_branch/_find_join/_branch_row/
  recover_interrupted_parallels；inline_wait 分支内联等待+心跳；
  join all/any/quorum+取消策略+超时+冲突记录；run detail 暴露分支。
- RED-5 → GREEN（wall-time 2.98s）；引擎 7 测试全绿；
  v2 survey 旧测试 storefront 适配与 profile fallback。

## 2026-08-12 · T0.5 判定器/校验器（ecd03ffa）

- gate_evaluator（fail-closed READY）；uat_report_validator
  （必填 IDs/段/inserted 判定）。RED-6/7/10 → GREEN。

## 2026-08-12 · T6 限流（98653f31）

- rate_limit.py（固定窗口+burst+Retry-After+审计，SQLite 持久化）；
  9 端点接入；rate_limit_api 管理（管理员+审计）；SystemStatus 表。
- RED-9 → GREEN；专项 9 测试全绿。

## 2026-08-12 · T5 shadow 纠偏（50398320）

- 脚本重写：extract_products/detail_products（sku_name）、hash、
  证据口径分类、负样本、p50/p95、CURRENT 恢复验证、诚实声明；
  实跑：真实 SKU 名解析、负样本 0 accepted、v2 报告生成、旧报告保留。
- standard_profile.current() 注入 USER_SELECTED_UAT_MODEL；
  shadow_report 优先 v2；训练页横幅；RED-8 → GREEN。

## 2026-08-12 · T4 UAT V2（33bd4bcb）

- scripts/v3_uat_rehearsal_v2.py：唯一 namespace、六角色、全实体
  inserted 校验、全题型+门头负证据+真照片、完整业务工作流、
  五 Agent 场景、新 Usage 100% 挂链核验、legacy 账本、BI 全链、
  Usage 下钻、权限矩阵、重启恢复、p50/p95、validator 强制。
- 执行期修复：_restore_ctx 重建输入/变量（_vars checkpoint）、
  loop body lint 可达、retry body 解析、report versions guard。
- 最终轮 39/39（ns uatv2_20260812170359_5vqash，54.8s）。

## 2026-08-12 · T7 浏览器验收（4e9bcc2f）

- 3 轮 QA（23 页）：修复训练页 USER_SELECTED_UAT_MODEL 横幅、
  /analytics/bi→/analytics/reports 重定向；55 截图；console 0
  （除诚实降级三项）；视口物理固定如实记录（browser_evidence.json）。

## 2026-08-12 · T8 全量验证与收口（22142f5f/0f447e81/本文档）

- hermetic 1359 passed / host_mps 6 passed / tsc 无错 / build 成功；
  CSS 变量契约修复（--accent→--accent-violet）。
- 服务生命周期 stop→DOWN / start→UP / doctor 全绿；训练进程无；
  tracked 树干净；integrity ok；迁移 048；CURRENT=prod_v4_best_r1、
  CURRENT.previous.json 在位。
- gate_evaluator：全条件 → READY_FOR_REAL_DATA_UAT；负例 BLOCKED_BY_P0。
- FINAL-REPORT.md 45 项完成。

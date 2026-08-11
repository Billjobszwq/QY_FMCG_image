# DECISIONS · Domain Packs V2

> 架构决定与替代方案。发现任务书与现场冲突时：现场证据优先，先在此披露，再兼容修订。

## 已继承（v2 设计冻结，不再重开）

- D-001 平台核心是 Agentic Graph+Loop，不是识别系统或传统 SaaS。
- D-002 ABOS 原生保存 workflow/run/event/evidence/usage 唯一事实。
- D-003 n8n 仅可选 connector executor（许可未确认前不启用，诚实标 blocked）。
- D-004 Dify 仅可选 AI subflow provider，不接管身份/权限/计费。
- D-005 先统一 Work/Event/Usage，再新增 Domain Pack。
- D-006 IAM 与 Master Data 先于问卷/BI/外勤/财务。
- D-007 模型识别结果进问卷只能是 suggestion，人工 final 才是业务答案。
- D-008 计费只来自 immutable Usage Ledger。
- D-009 第三方引擎与模块均经 Adapter SPI，不得绕过 Policy。

## 本轮新增

### D-010 rq_v2 审核族与 legacy dry-run 通过 supersession 账本移出当前待办

- 背景：P0-001 现场复现 `/api/v1/workitems` count=256，其中 250 项 rq_v2
  审核与 4 个 legacy dry-run 仍作为当前待办。
- 决定：新增 append-only `work_item_supersession_v1` 账本；投影默认
  `projection=current` 排除被取代族，`history`/`all` 可回看；历史行不删。
  rq_v2 取代依据 docs/README 2026-08-09（SUPERSEDED_FOR_DEMO_TRAINING，
  LS22 唯一有效人工入口）；legacy dry-run 以命令含当前 CLI 不支持的
  `--dataset/--budget-minutes` 为判据（CODEX 手册 §5.6-6）。
- 替代方案：直接删除旧任务/改默认分页——拒绝（违反不可变历史原则）；
  前端隐藏——拒绝（API/Agent 仍会读到假待办）。
- 影响：旧测试 test_review_status_source 两个用例改用未被取代的 rq_v3
  验证同一机制（契约变更，非弱化断言）。

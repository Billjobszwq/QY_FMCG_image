# STATUS / DECISIONS / ISSUES

更新时间：2026-08-11（实施 Agent 接管后）。
详细决定见 `DECISIONS.md`，问题清单见 `ISSUES.md`，任务状态见 `IMPLEMENTATION-LIST.md`。

## 当前 Gate（唯一）

`PHASE_A–F_CLOSED_G1–G8_PASSED → T9 系统级收口待开工`（G9）。

- Phase A 证据：`4af64f2d` → `79b3a534` → `15a39325`；浏览器四视口 8/8。
- Phase B 证据：`13106320`；实跱全链 ID 对账 + 失败同链恢复。
- Phase C 证据：`aa7ba378`；模板实跱贯通 + Studio 6/6。
- Phase D 证据：`55e71271`；双 test fixture 客户隔离实跱证明。
- Phase E 证据：`fde1b4ae`；样板问卷实跱 E2E（评分 13→15 v2）。
- Phase F 证据：`c0be4098`；BI 异常闭环/外勤全链/账单下钻实跱；
  hermetic 1246 passed；浏览器验收截图齐全。

不是 `READY_FOR_USER_ACCEPTANCE`：T9 收口（Z-1 全量交叉验证、Z-2 六个
Domain Agent、最终验证套件、四手册更新）完成前不得声称用户验收就绪。

## 已冻结决定

- D-001：平台核心是 Agentic Graph+Loop，不是识别系统或传统 SaaS。
- D-002：ABOS 原生保存 workflow、run、event、evidence、usage 唯一事实。
- D-003：n8n 仅可作为可选 connector executor，启用前完成 Embed/Enterprise 许可评估。
- D-004：Dify 仅可作为可选 AI subflow provider，不接管客户、权限、会话、任务和计费。
- D-005：先统一 Work/Event/Usage，再新增 Domain Pack。
- D-006：IAM 与 Master Data 先于问卷/BI/外勤/财务。
- D-007：模型识别结果进入问卷时只能是 suggestion，人工 final 才是业务答案。
- D-008：所有计费来自 immutable Usage Ledger，不能从页面计数临时反推。
- D-009：第三方引擎和模块都通过 Adapter SPI，可插拔但不能绕过 Policy。

## 当前未关闭问题

- P1：P1-002 Manifest 全量交叉验证（部分关闭，Z-1 完成）；P1-003 App 手写
  路由（未关闭，Z-1 ModuleUIRegistry）；P1-004 主管工具化规划（未关闭，Z-2）；
- P2：便签 localStorage、event polling、profile 信息过载；
- 业务：五个 Domain Pack 均已 live；待 Z-2 六个 Domain Agent 独立身份化。

## 现场基线（2026-08-11 实时核验）

- HEAD `d00953ad`，分支 `feat/nextgen-training-cycle-v2`，tracked 干净；用户未跟踪资产零触碰。
- 服务 8091/8092/8300/8400 全部 UP；DB integrity ok（63 表，迁移至 030）；production `prod_20260805_v5_r1` 未切换；无训练进程。

## 本轮未做

未 merge/push/deploy；未启动训练；未切换 production；未删除或暂存用户资产。

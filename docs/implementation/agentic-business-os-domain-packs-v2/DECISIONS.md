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

（暂无；执行中发现现场冲突或需新决定时追加，格式：编号/背景/决定/替代方案/影响。）

# SKU 长尾治理 + Agent 底座 V1

> 任务书：本目录 AGENT-EXECUTION-PROMPT.md（原样保存）。
> 分支 `feat/nextgen-training-cycle-v2`；起点 HEAD `e95e3ca`。
> 内核保持：Graph+Loop + 独立领域模块 + 统一事实源 + 标准能力接口 + Hook + Agent 编排 + 证据链。
> FMCG 识别仅是第一个 Domain Pack。

## Superseded 关系
- 旧 `5+5+250` 人工门 → `SUPERSEDED_FOR_DEMO_TRAINING`（不删除队列/项目/行/证据），
  替代为 `demo_micro_gold_v1`（region/mask 单位，120–300 region，与训练并行）。
- `graph-loop-training-control-v1` / `nextgen-four-model-training-loop-v2` 仍为历史契约证据；
  本目录接管实施入口。

## 文档
- 01 现场与 Bug 审计；02 长尾数据政策；03 SAM 与四模型设计；
- 04 多 Agent/黑板/记忆；05 Web/API 契约；06 执行计划与门禁；
- execution/ 六件套（IMPLEMENTATION-LIST/STATUS/DECISIONS/ISSUES/EXECUTION-LOG/ACCEPTANCE）。

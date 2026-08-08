# CORRECTION-DECISIONS
- D1 Gate 纠正为 PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED。
- D2 reconciliation 幂等追加，hash 冲突 fail-closed。
- D3 历史 cycle 节点经 reconciliation event 标记，不伪造执行。
- D4 Supervisor 默认 rules_fallback，provider 可替换，不伪装 LLM。
- D5 M3 消融同 grouped split/同预算/early stop；random 82.4% 仅泄漏证据。
- D6 KB gate：coverage 100% & recall@8≥90% 才 M4 pilot。
- D7 每次训练九要素快照（source commit/dirty/launcher hash/command/env/
  manifest/base hash/config/seed）。

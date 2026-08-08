# 07 平台真实接通 + 训练纠偏

## Gate 纠正
`FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_EVALUATION`
→ **`PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED`**（数据库/API/Web 一致）。

## 制品状态纠正（Task 1，冻结）
M1/M2=SMOKE_ONLY_NOT_CANDIDATE；M3 random=INVALID_FOR_BUSINESS_EVAL_LEAKED_SPLIT；
M3 grouped=GROUPED_BASELINE_NOT_CANDIDATE；M4=PILOT_NOT_EVALUABLE_KB_COVERAGE_ZERO；
SAM v1/v2=EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE。制品不删。

## reconciliation（Task 2）
scripts/reconcile_platform_facts.py：幂等追加；12 字段；hash 冲突 fail-closed；
四方对账（磁盘=DB=API=Web）。m026 三注册表。

## Cycle（Task 3）
sku_long_tail_nextgen_cycle_v1：19 节点；历史 10 节点经 reconciliation event
标记（不伪造重新执行）；幂等键；重启可恢复；taskboard 卡片真实投影。

## Supervisor（Task 4）
/api/agent/v1/* 全接口；rules_fallback provider（标注，不伪装 LLM）；
10 意图；UIIntent 白名单；高风险审批；不切生产。

## 训练范围（Task 8）
canonical38（mapped，grouped）/ research83（全 83，实验标记）。
pending 45 裁决包：pending_sku_decision_pack.json/md（自动材料，人工裁决）。

## 训练（Task 9/10/11）
M1 pilot 5ep mAP50 0.077（九要素快照）；M2 pilot 5ep 运行中；
M3 消融 E1-E5（canonical38 grouped，同预算，early stop）；
KB canonical38 → recall gate（coverage 100% & recall@8≥90%）→ M4 pilot。

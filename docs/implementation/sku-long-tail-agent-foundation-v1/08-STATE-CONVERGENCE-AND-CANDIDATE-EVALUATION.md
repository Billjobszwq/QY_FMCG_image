# 08 状态一致性收口与候选模型独立评估

## 基线（2026-08-09 重验，禁沿用旧报告数字）
HEAD 69451495；blackboard=23；memory=4；cycle_nodes=25（19 逻辑+6 重复）；
artifacts=12；M1/M2=PILOT_NOT_CANDIDATE_YET（报告内 candidate=true 冲突）；
M3 E5/M4=CANDIDATE_PENDING_EVAL（过早）；Cycle=TRAINING_CYCLE_ACTIVE（错）。

## 统一候选状态（7 态）
SMOKE_ONLY_NOT_CANDIDATE / PILOT_NOT_CANDIDATE / PILOT_PENDING_EVALUATION /
CANDIDATE_PENDING_EVALUATION / CANDIDATE_REJECTED /
CANDIDATE_ACCEPTED_FOR_SHADOW / PRODUCTION_APPROVED。

## 状态投影
- training_cycle_node_state_v2：UNIQUE(cycle_id, logical_node)，乐观版本，
  done 禁回退 pending（除非 reopen 事件）；历史表保留。
- task_state_projection_v1：UNIQUE(project, cycle_id, logical_task_key)。

## Gate
开始：MODEL_PILOTS_READY_AWAITING_CANDIDATE_EVALUATION；
完成 M3 独立测试+M4 三版本评估后：EVALUATED_CANDIDATES_READY_AWAITING_MICRO_GOLD；
禁 FOUR_CANDIDATES_READY / PROMOTION_READY / PRODUCTION_READY。

## M3 独立评估
canonical38_train_val_test_v2（70/15/15 grouped，五键零交叉）；只重训 E1/E5；
test 训练后仅跑一次；综合优先级 accepted precision→macro F1→worst-decile→top1→calibration→latency；
各有优劣则保留双候选分档。

## M4 独立评估
base / 旧 cropped adapter / 新 real-candidate adapter 三版本；独立 grouped holdout；
禁重训；新 adapter 有明确收益才升 CANDIDATE_PENDING_MICRO_GOLD。

# STATE-CORRECTION-LOG

- T0 基线：HEAD 69451495；blackboard 23；cycle_nodes 25（重复 6）；
  .gitignore +.gstack/ 单独提交（有意，披露）。
- T1 m028 投影表；backfill 19 节点（16done/3pending）；历史 25 行保留；
  Cycle 状态 TRAINING_CYCLE_ACTIVE→MODEL_PILOTS…→EVALUATED_…AWAITING_MICRO_GOLD。
- T2 task_state_projection_v1：done7/waiting6；blackboard +9 修正事件（32）。
- T3 Overview CurrentStatePanel；250 卡 superseded 标注；Supervisor 250 问答。
- T4 7 态统一；M1/M2 报告 candidate=true→false；Registry 全一致。
- T5 Profile 10 个引用最新 Artifact；shadow 引真实 production bundle（已注册）。
- T6 tvt_v2：5,122 组（SHA union-find 合并跨组重复）；train 8144/val 1692/test 1764；
  38 类全 test min19；E1 top1 .9484 F1 .94 worst .766 ECE .016 acc@p90 .986；
  E5 top1 .9461 F1 .9365 worst .719 ECE .013 acc@p90 .985 → 双候选分档。
- T7 M4 三版本：base .475 / 旧 .656 / 新 .828；recall@1 .789 @5 .991 @8 1.0；
  abstain 弱项 false_accept 8 披露；新 adapter→CANDIDATE_PENDING_MICRO_GOLD。
- T8 m1_m2_data_gap：894 图/5543 regions；small 37%；补采≥3000 全场景。
- T9 hermetic 1107 绿（修依赖方向：projection 移 platform）；host 6 passed。
- T10 对比度修复（抽屉/任务板/面板/表头）；六问答全过（DOM+截图2张；
  3 张截图因窗口 hidden 不可拍，DOM 证据完整）。

# 候选模型证据链收口 + demo_micro_gold_v1 启动指令

你现在接手项目：<legacy-workspace>

本次不是重新训练任务，而是一次性完成：
1. 候选模型、评估报告、数据库、API、Web 的状态一致性收口；
2. 真实复核 Qwen3-VL 三版本评估；
3. 修复当前 Profile 引用错误；
4. 启动新的 demo_micro_gold_v1 人工金标准任务。

不要再重复旧的 250 张审核流程，不要继续无效循环。

## 三、安全边界（本轮严禁）
1. 重新训练 M1/M2/M3/SAM/Classifier/Qwen；2. 启动新 QLoRA；3. 切换 production；
4. merge/push/deploy；5. 删除/移动/覆盖旧模型/报告/DB 记录；6. 清理未跟踪资产；
7. 修改/删除 .superpowers/；8. 恢复旧 250 为活动任务；9. 伪造 human_final/gold_verified；
10. 使用文件名/目录名/GT 帮助候选检索或推理；11. 为过 Gate 修改指标/降门槛/伪造证据。
生产保持 prod_20260805_v5_r1。起始 Gate=CANDIDATE_EVIDENCE_CONVERGENCE_REQUIRED；
全部机器门禁通过后才可 MICRO_GOLD_READY_AWAITING_HUMAN_REVIEW。

## 四、先复现问题（红测试先行）
P0-1 Profile 引用错误 M3 权重（应 m3_tvt_e1_v2/e5_v2，旧 ablation 不得冒充）。
P0-2 M4 三版本报告证据不足（tokens=0、p95 0.2-0.3s、prediction 非 canonical ID、
缺哈希/raw output/逐样本耗时、未注册 Evaluation Registry）；不得直接接受 0.828。
P1-1 Cycle/Taskboard 冲突（m3_independent_test、m4_adjudication_eval 仍 waiting）。
P1-2 hermetic 三测试依赖真实 MPS（test_repeat_enqueue_returns_same_job /
test_approve_no_job_no_compute / test_enqueue_creates_job_with_run_command）；
生产 G0 不放宽，业务测试用显式 fake G0 evidence。
P1-3 主管抽屉仍显示过期 KB blocker；旧事件保留，当前视图正确处理 supersedes。

## 六、M3 收口
m3_tvt_e1_v2/e5_v2 = CANDIDATE_PENDING_MICRO_GOLD；
m3_ablation_e1_v1 = EXPERIMENTAL_SUPERSEDED_BY_M3_TVT_E1_V2；
m3_ablation_e5_v1 = EXPERIMENTAL_SUPERSEDED_BY_M3_TVT_E5_V2；旧文件全保留。
Profile：canonical38_classifier_e1→m3_tvt_e1_v2；e5→m3_tvt_e5_v2；
shadow_compare→prod_20260805_v5_r1_bundle+m3_tvt_e1_v2；均 disabled；M1/M2 PILOT_NOT_CANDIDATE。
Profile 唯一事实源：DB 7 条 vs API 10 条问题必须解决；旧表退出需标 legacy/read-only。

## 七、M3 独立测试登记（evaluation_registry）
m3_tvt_e1_v2_independent_test / m3_tvt_e5_v2_independent_test：
artifact_id、SHA256、dataset manifest SHA、split audit SHA、source commit、
dirty diff、launcher hash、seed、train/val/test 统计、test-once 声明、
metrics path/hash、evidence level、protocol version。禁把旧 ablation 指标登记为 TVT 指标。

## 八、M4 真实复核（只评估不训练）
MLX 独占；.venv_mlx_vlm；先 12-20 条 bounded smoke，不过即停。
三版本同 holdout/候选/prompt/解析规则。防 GT 泄漏：推理前转无语义 sample_id；
候选仅真实链（OCR→embedding→KB→top-k）。逐样本记录：sample_id、image SHA、
leakage_group、candidate list/scores、prompt hash、model/adapter hash、
processor/library 版本、raw output、parsed canonical、abstain/accepted、wall time、
token 数（不支持写 unsupported 禁填 0）、parse error、escape。
汇总：recall@1/5/8、Top-1、macro-F1、accepted precision、coverage、
abstain P/R、false accept/reject、pending false accept、escape、p50/p95、吞吐、错误账本。
登记 Evaluation Registry；新 adapter 最多 CANDIDATE_PENDING_MICRO_GOLD。

## 九、Cycle/Taskboard/Blackboard 收口
m3_independent_test=done；m4_adjudication_eval=done；AwaitingIndependentEvaluation=done；
Cycle 17/19（pending 仅 DemoEvaluation、AwaitingProductionDecision）；
Gate=MACHINE_EVALUATION_COMPLETE_AWAITING_MICRO_GOLD；25 行历史保留；
Blackboard 旧 blocker 不删，写 Resolution/supersedes；当前视图只显示有效事件；
KB 未建不再显示为活动阻断；250 继续 SUPERSEDED，不进待办/活动板/完成率。

## 十、测试隔离
红测试证明无 MPS 失败→fake G0 修复→hermetic 全绿 + host MPS 全过；
分别报告 passed/failed/skipped/deselected，禁把 deselected 当 passed。

## 十一、demo_micro_gold_v1
200 region：120 canonical + 40 pending/unknown + 20 困难 + 20 负样本。
泄漏门禁：photo_id/exact SHA/normalized store/store alias/session/
leakage_group_id/symlink target；与 train/val/test/QLoRA 集重叠 fail-closed；
不足 200 不降门禁、不复用 250、不伪造，报告缺口。
LS 新项目 demo_micro_gold_v1_blind：默认不展示 prediction；canonical taxonomy 可见；
pending/unknown 选项可见；图片 region 可加载；文件名不暴露 SKU；初始 pending；不伪造人工。
流程：200 主审；确定性抽 40 第二人盲审；分歧第三人仲裁；一致=human_final；仲裁后=gold_verified。
导入后 Gate=MICRO_GOLD_READY_AWAITING_HUMAN_REVIEW，停止。

## 十二、Web/Agent 验收
Overview/Training/Recognition/Taskboard/Drawer 真实状态；Supervisor 八问；
切换生产必须拒绝；浏览器截图完整清晰（Overview/Training/Recognition/Taskboard/
Supervisor/LS taxonomy/blind 无 prediction）。

## 十四、完成门（全满足才 COMPLETE，否则 BLOCKED/DONE_WITH_CONCERNS）
Profile 引用 tvt；旧 ablation superseded；M3 两项登记；M4 三版本 raw+证据+登记；
任务板不再 waiting；Cycle 17/19；Blackboard 无失效 blocker；hermetic/host 全过；
integrity ok；API/DB/Web/Profile 一致；四服务健康；production 未切换；
micro-gold 建立导入；人工完成数真实（未审=0）；Gate=MICRO_GOLD_READY_AWAITING_HUMAN_REVIEW；
工作树无非预期 tracked 修改；手册+文档更新。

## 十五、最终报告 45 项（顺序）
HEAD/branch/worktree；commit 链；阅读文件；初始复现；Profile 前后；M3 新旧状态；
M3 Registry 记录；M4 smoke；M4 三版本加载证据；base/old/new 指标；raw/token/latency；
GT 泄漏检查；M4 结论；Cycle 前后；Taskboard 前后；Blackboard supersedes；250 状态；
Artifact 数+disk consistency；Profile 数+映射；Registry 数；hermetic；host；TS/Vite；
integrity；服务健康；Web/API/DB 一致；八问；micro-gold 来源；200 构成；泄漏结果；
LS 项目 ID；taxonomy 可见；blind 无 prediction；人工完成数；截图路径；production 声明；
未启动新训练声明；未关闭问题；Gate；用户下一步唯一事项；文档证据路径。
用户下一步只需：进入 Label Studio 完成 demo_micro_gold_v1 真实人工审核。

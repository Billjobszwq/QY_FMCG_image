# 01 · 统一终态状态机与不变量

## 对象状态机

- BusinessRun：queued→running→{succeeded | failed | cancelled}；
  running⇄paused；running→waiting_human/waiting_timer→running；
  终态三态互不可达（CAS by set_business_run_status）。
- 主 WorkItem：todo/running→done（run succeeded）| blocked（run
  failed）| cancelled（run cancelled/rejected）。
- Approval WorkItem：approval→done（approved）| cancelled（rejected/
  run cancelled），decision/actor/timestamp 留痕。
- WorkflowNodeExecution：pending/running→succeeded/failed/skipped。
- WorkflowTimer：pending→fired | cancelled（run 终态时未到期一律
  cancelled；到期触发前必须复查 run 终态）。
- WorkflowBranch：pending/running→completed | failed | timeout |
  cancelled（run 终态时未结束分支一律 cancelled）。
- DeadLetter：仅 run failed 追加；Evidence/Usage 追加式不可变。
- Current Projection：终态 work 不得被事件派生状态回退。

## Run 终态对应关系（不变量）

- succeeded：主 work=done；approval=done；必须分支 completed；
  timer fired/cancelled；当前 error 清空（历史留事件）。
- failed：主 work=blocked；失败节点 failed；未完成分支/待触发 timer
  cancelled；DeadLetter+Evidence；允许 retry。
- cancelled：主 work=cancelled；approval=cancelled；pending timer
  cancelled；pending/running 分支 cancelled；后台线程不得回写；
  Evidence/Usage 保留。
- rejected（人工拒绝）：明确 Decision；approval=cancelled(rejected)；
  run=cancelled 且事件 human_approval.rejected 留痕。

## 实现契约

- 统一 `finalize_run(run_id, status, ...)`：CAS 抢占终态（已终态则
  no-op 返回 False），同一事务内收敛全部关联对象并发终态事件。
- 取消令牌 = run 状态本身；分支 inline wait 心跳与节点提交前检查。
- reconcile/projection drift 修复：run 终态时以 run 终态推导 work，
  禁止把终态 work 回退为活动态。

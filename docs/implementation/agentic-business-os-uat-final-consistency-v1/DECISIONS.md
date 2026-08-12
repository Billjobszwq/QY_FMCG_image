# DECISIONS（追加式）

| ID | 决定 |
|---|---|
| D-001 | 终态收敛统一经 finalize_run（CAS：终态不可互覆）+ run.cancelled/workflow.* 终态事件补发；历史漂移经追加式 converge 修复（state.converged 事件），不删历史 |
| D-002 | 取消为协作式：run 状态即取消令牌；inline wait/分支心跳/节点提交前检查；ThreadPool 剩余任务结果丢弃 |
| D-003 | fixture 结构隔离：data_scope/visibility 列 + 投影过滤 + test-data archive API；名字前缀仅为回填识别线索，不是隔离机制本身 |
| D-004 | Gate 仅由 evaluate_gate_from_evidence 从 store/报告/测试/服务/浏览器证据计算，写 .eval/*/gate.json；文档只引用 |
| D-005 | Agent 定义缺失也进统一调用链：先建 failed run/work/evidence（AGENT_DEFINITION_NOT_FOUND），后返回 409 |
| D-006 | 拒绝（rejected）为明确 Decision：事件 human_approval.rejected + approval work cancelled(rejected) + run cancelled；不与模糊 cancel 混用 |

# ISSUES

| ID | 级别 | 状态 | 摘要 | 关闭证据 |
|---|---|---|---|---|
| UFC-001 | P0 | CLOSED | Run/Work 终态漂移（cancelled run 主 work 活动态；succeeded run approval 残留） | finalize_run 原子 CAS 收敛（条件 UPDATE）+ 投影/reconcile 终态保护；test_ufc_red_state 全绿；UAT V3 终态收敛断言通过；reconcile drift=0 |
| UFC-002 | P0 | CLOSED | Gate 非证据驱动 | evaluate_gate_from_evidence 从 store/报告/账本/测试/服务/浏览器证据计算，写 .eval/v3_uat_v3/gate.json；/api/v1/control/gate 只读展示；SystemStatus 页可展开证据 |
| UFC-003 | P1 | CLOSED | UAT 主工作流缺 model/capability 节点 | 主工作流 command 节点真实调用 vision.recognition.create（继承 customer/project/correlation/parent_run），UAT V3 断言 sub_run succeeded |
| UFC-004 | P1 | CLOSED | 异常追问链未执行 | UAT V3：hit=true→Analytics Agent 追问（run 链）→人工回答→resolved→报表 v2；ano-778e77a2b7ed 等 |
| UFC-005 | P1 | CLOSED | Agent 失败无账本 | _record_definition_failure：failed BusinessRun+blocked work+evidence+usage（AGENT_DEFINITION_NOT_FOUND）；AgentCenter 失败账本 UI 红色展示 |
| UFC-006 | P1 | CLOSED | UAT fixture 污染运营投影 | 迁移 049 data_scope/visibility + TestDataService mark/archive/converge-legacy；首页待办 0；residue=0；测试与证据页可查 |
| UFC-007 | P0 | CLOSED | approval 子待办不随批准/拒绝/取消关闭 | finalize_run 收敛 approval；approve_run 批准→done/拒绝→cancelled(rejected 事件)；UAT V3 断言通过 |
| UFC-008 | P0 | CLOSED | 取消后后台分支继续执行/回写 | 协作式取消（节点/分支/心跳检查）+ 原子 CAS；UAT V3 取消后 run/主 work/分支全 cancelled 且 6s 后不回写 |

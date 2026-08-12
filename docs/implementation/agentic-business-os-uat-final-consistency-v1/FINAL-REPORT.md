# FINAL REPORT · UAT 终态一致性与证据闭环（41 项）

最终 Gate：`READY_FOR_REAL_DATA_UAT`（机器计算，见
`.eval/v3_uat_v3/gate.json`，evaluator 2.0.0，20/20 checks ok）。
不得写 ACCEPTED / COMPLETE / PRODUCTION_READY。

1. **HEAD/branch/worktree**：HEAD `6664022f`（含外部并行提交的
   TaaS 演示文档 commits，已审计不覆盖）；branch
   `feat/nextgen-training-cycle-v2`；单 worktree；tracked 干净。
2. **commit 链**（本轮）：`b9a1723e`(T10a driver) → `53022a54`(T10b
   CAS/语义) → `6664022f`(T9/T10c UI+gate+CDP)；前置：T0 治理+红测试、
   T4 隔离、T7/T8 链、validator/gate 各 commits。
3. **阅读清单**：GLOBAL_AGENT_ROUTING、AGENTS.md、CODEX/USER/
   OPERATOR/MODULE-DEV 手册、V3 目录全部、UAT-contract-correction-v1
   全部、workflow/runtime/gate_evaluator/validator/rehearsal_v2/v3、
   近 30 commits、DB schema/迁移/服务/CURRENT/制品 hash。
4. **初始状态漂移**：4 个 cancelled run 主 work 活动态（run-5be533c2e28e/
   df31c2f6b8a3/1d87e49e98f7/c858ce98a621）；3 个 succeeded run approval
   残留（run-a8984d09e2e3/f0529cac44db/6e7fdeec3123）；首页 todos
   blocked=3/cancelled=4 污染；agent 失败 run=0；15 uat 客户无隔离。
5. **红测试**：tests/platform/test_ufc_red_state.py 14 项首跑 RED
   （终态不收敛/无 CAS/无失败账本/无证据 Gate）→ 全 GREEN。
6. **状态机**：01-STATE-MACHINE-CONTRACT.md——BusinessRun/主 Work/
   Approval/NodeExecution/Timer/Branch/DeadLetter/Evidence/Usage/
   Projection 状态机与三终态不变量。
7. **取消竞态根因**：finalize 的 SELECT+UPDATE 非原子，并发下
   succeeded 覆盖 cancelled；后台分支无取消检查；reconcile 按不完整
   事件流回退终态。
8. **取消后终态**：原子条件 UPDATE CAS；UAT V3 断言 run/主 work/
   分支全 cancelled，6s 后不回写（run-cce855a74e1e 类）。
9. **Approval 子待办终态**：批准→done（decision/actor 留痕）；拒绝→
   cancelled + human_approval.rejected 事件；run 取消→approval 收敛。
10. **Timer 终态**：finalize 将 pending timer 置 cancelled；_fire_timer
    触发前复查 run 终态；UAT V3 重启恢复 run succeeded。
11. **Branch 终态**：finalize 将 pending/running 分支 cancelled；quorum
    达成后剩余 cancelled；UAT V3 分支表全收敛。
12. **retry 终态**：failed→retry 成功→run succeeded + 主 work done，
    投影无 blocked 残留（UAT V3 5.3）。
13. **projection rebuild**：终态保护（终态 work 不回退）+ fixture 双
    保险排除；rebuild 两次 hash 一致；reconcile drift=0。
14. **fixture 隔离**：迁移 049（data_scope/visibility/superseded_at/
    test_run_id）；TestDataService mark/archive/converge-legacy；
    API /api/v1/test-data/*；投影排除 uat_fixture。
15. **operational current 残留**：0（归档后；/status 页与
    test-data/namespaces 双证）。
16. **evidence-driven Gate**：evaluate_gate_from_evidence 20 项检查
    （P0/P1、validator、drift、usage 完整率、agent 账本、storefront
    负正例、parallel、必备节点、anomaly 链、rate limit、V4 诚实性、
    服务、integrity、测试、浏览器、模型、训练进程）→ gate.json；
    负例（P0=1）→ BLOCKED_BY_P0 已验证。
17. **validator 负例**：failed>0/check 失败/意外 4xx-5xx/终态残留/缺
    model|command/anomaly 缺链/Agent 账本缺/Usage 未挂链/截图文件缺/
    服务不健康/CURRENT 非 v4/训练进程 → 全部拒绝且退出码非 0。
18. **主工作流节点**：trigger/transform/condition/wait/parallel/join/
    loop/human_approval/agent/command（wf-44f211a575）。
19. **model/capability 执行**：command 节点
    vision.recognition.create 工作流内执行，sub_run=
    run-dbd6a66c25d44547 succeeded，继承 customer/project/
    correlation/parent_run。
20. **V4 run/evidence/usage**：recognition_task=
    0c1a62362b98f8ffb6dc971f0e3886a7；evidence=evid-e2ae80fa99104fb0；
    usage=usage-51dd884231f643b7（model_compute_ms 106.84）。
21. **异常 ID**：ano-bed100e6b474（recognition.photos ge 0 命中）。
22. **Agent 追问**：follow_up=run-9d49e6b8a27f（analytics_agent，
    follow_up_question+followup_agent_run_id 持久化）。
23. **人工回答**：/anomalies/{id}/answer（人工 session+CSRF；Agent
    不得代答）→ resolved。
24. **报表版本变化**：rep-24d238dc625b versions=2（回答触发 v2 draft）。
25. **Agent 失败 Run**：run-6430a7d1730b（no_such_agent_u3，
    AGENT_DEFINITION_NOT_FOUND，409）。
26. **Agent 失败 Evidence**：evidence_bundle:evid-298ba80668a1。
27. **Agent 失败 Usage**：usage-5ed14b916ce0（run_status=failed 挂链）。
28. **Usage 完整率**：本轮 agent_call 6/6 挂 run/work（100%）。
29. **浏览器 QA**：DOM 12 页检查点全过（待办 0/审批 0/失败账本红色/
    Gate 区块/prod_v4_best_r1+橙色横幅/anomalies resolved）；未解释
    console error 0；CDP headless Chrome 截图 17 张（真实 CSS 宽
    1440/1280/1024/768，文件名含宽度，不冒充物理视口）；内置截图
    工具会话级故障已多会话复现并如实记录。
30. **hermetic**：1386 passed, 1 skipped, 0 failed。
31. **host MPS**：6 passed。
32. **typecheck/build**：tsc --noEmit 无错；vite build 成功。
33. **SQLite/migration**：integrity ok；迁移 050 幂等（多次 restart）。
34. **服务恢复**：stop→全 DOWN / start→四服务 UP / doctor 全绿；
    重启后持久 timer run succeeded；CURRENT 保持 prod_v4_best_r1。
35. **当前模型**：prod_v4_best_r1（detector 84bf993618937700…；
    CURRENT.previous.json=prod_20260805_v5_r1 回滚在位；
    USER_SELECTED_UAT_MODEL 横幅）。
36. **无训练声明**：pgrep 训练进程=0；训练未获授权（training_
    authorized=false 页面如实显示）。
37. **未关闭问题**：无 P0/P1 遗留（ISSUES UFC-001..008 全 CLOSED）。
    诚实披露：① 内置浏览器截图工具故障（已用 CDP 替代）；② 地理编码/
    瓦片无 Key（degraded）；③ ml_backend disabled（非关键，诚实状态）。
38. **Gate 机器文件路径**：/Users/zhangweiqi/Documents/QY/项目/
    LLM-Image/.eval/v3_uat_v3/gate.json（+ report.json +
    browser/browser_evidence.json + test_report.json）。
39. **最终 Gate**：`READY_FOR_REAL_DATA_UAT`。
40. **用户唯一下一步**：用真实客户/地址/问卷/照片执行 05-UAT 手册真实
    数据 UAT（可选配置 GEOCODER_PROVIDER/AMAP_API_KEY/
    TENCENT_MAP_KEY/MAP_TILES_URL）；模型准确率晋级须先建独立人工
    真值集再走 shadow→评估→审批链。
41. **证据总入口**：治理目录 docs/implementation/agentic-business-os-
    uat-final-consistency-v1/（00 审计/01 状态机/02 Gate/03 协议/
    STATUS/ISSUES/DECISIONS/LIST/EXECUTION-LOG/FINAL-REPORT）；
    证据 .eval/v3_uat_v3/。

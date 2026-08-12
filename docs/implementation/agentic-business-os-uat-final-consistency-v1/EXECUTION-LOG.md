# EXECUTION LOG（追加式）

## 2026-08-12 · T0 现场复现

- HEAD 6cbca9c0 与预期一致；四服务 UP；无训练。
- DB 复现：4 cancelled run 主 work 活动态；3 succeeded run approval
  残留；agent.invoke failed=0；15 uat 客户；首页 todos 含 3 running+
  1 waiting+3 blocked+3 approval 漂移残留。
- 取证 run-df31c2f6b8a3：cancel 后 20s 分支仍 parallel_joined；
  work 在后续 reconcile 时段被推回 running。

## 2026-08-12 · T1–T3 终态状态机与取消竞态

- finalize_run：原子条件 UPDATE CAS（终态互不可覆）；收敛主 work/
  approval/timer/branch；终态事件 workflow.succeeded/failed/cancelled
  (+run.cancelled)。
- 协作式取消：_run_nodes 每节点前检查、_exec_branch 每节点前检查、
  inline wait 心跳检查；paused 不启动新节点。
- approve_run：批准→approval done（decision/actor 留痕）；拒绝→
  human_approval.rejected 事件 + approval cancelled + run cancelled。
- 红测试：test_ufc_red_state.py 14 项（含并发 finalize 单方胜）。

## 2026-08-12 · T4 fixture 隔离

- 迁移 049：md_customer/business_run/work_item 增加
  data_scope/visibility/superseded_at/test_run_id。
- TestDataService：mark/archive/converge-legacy（追加式，不删除）；
  投影双保险排除 uat_fixture；drift 扫描排除 fixture。
- 真实库：converge-legacy 归档 17 客户；首页待办 0；residue=0。

## 2026-08-12 · T5/T6 证据驱动 Gate 与 validator

- evaluate_gate_from_evidence：20 项证据检查，写 gate.json；
  /api/v1/control/gate 只读；SystemStatus 页展示+展开。
- validator：failed>0/check 失败/意外 4xx-5xx/终态残留/缺必备节点/
  异常链/Agent 账本/Usage 挂链/截图文件/服务/模型/训练进程 全项拒绝。

## 2026-08-12 · T7–T9

- command/model 节点继承 customer/project/correlation/parent_run；
  失败以输出状态路由到人工接管（fail_on_error 可选节点级 raise）。
- 异常链：check_anomaly hit→Analytics Agent 追问（run 链持久化）→
  人工回答（Agent 不得代答）→resolved→报表新版本。
- Agent 失败账本：_record_definition_failure；/api/v1/agents/runs；
  AgentCenter 失败账本卡片（红色）。

## 2026-08-12 · T10 UAT V3 + QA + 全量

- UAT V3：47/47（ns uatv3_*）；主工作流含 command 识别（sub_run
  succeeded）；异常链 ano-778e77a2b7ed resolved+报表 v2；拒绝/取消/
  重试终态断言；parallel wall 2.02s；重启恢复；residue=0；drift=0。
- 浏览器：内置截图工具会话级故障（about:blank 亦超时，已多会话复现）
  → 改用 CDP headless Chrome 真实视口截图 17 张（1440/1280/1024/768）
  + DOM QA 12 页检查点全过、未解释 console error 0。
- 全量：hermetic 1386 passed / host_mps 6 passed / tsc 无错 / build 成功。
- Gate：READY_FOR_REAL_DATA_UAT（20/20，gate.json）。

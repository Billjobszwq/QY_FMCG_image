# ISSUES · Scope Integrity V3

> 格式：`| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |`

| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |
|---|---|---|---|---|---|---|
| SI3-001 | P0 | OPEN | 隔离只看行自身列，父链 effective scope 泄漏全部漏检（media=24/work=8/recognition=5/usage=89） | before_audit.json；R1/R2/R3/R6/R15 红 | OPERATIONAL_FILTER 不追父链；operational_leakage 只查自身列 | Scope Graph V3 effective scope 扫描 |
| SI3-002 | P0 | OPEN | Gate 2.1 假阳性 READY（scanner except/continue + 静态 JSON + 无 freshness） | gate.json READY vs 审计计数；R13/R14 红 | gate_evaluator 吞异常；control/gate 只读文件 | Gate 3.0 fail-closed + freshness |
| SI3-003 | P0 | OPEN | test_run_id 无 registry 校验；INSERT OR REPLACE 覆盖 namespace；先 commit 再 bind | R9/R10/R12 红 | resolver 不查 uat_test_run_v1；test_data.py 写法 | Test Run registry fail-closed + 事务原子 |
| SI3-004 | P0 | OPEN | Agent 工具创建 BI/问卷/识别对象不透传 scope（BI draft 5+ 条 operational） | before_audit bi=5/11；R4 红 | runtime._exec_tool 不带 ctx；bi_report_spec 无 run_id 列 | 工具调用透传 ExecutionContext + 结构列 |
| SI3-005 | P0 | OPEN | 失败 Agent 路径吞 scope 异常，账本落 operational（5 轮） | before_audit failed_agent=5；R5 红 | _record_definition_failure 的 resolve except 兜底 operational | 先解析 scope 再查定义，禁止吞 |
| SI3-006 | P0 | OPEN | Usage/财务 API 与汇总零 scope 过滤（89 条 fixture 计入运营） | before_audit usage=89/invoice=2；R6 红 | usage_api/finance 无 effective 口径 | effective_scope 查询口径 + attribution ledger |
| SI3-007 | P1 | OPEN | terminal Run 下 node 未收敛（39 条）；Gate 不查 node 层 | before_audit node=39；R8 红 | cancel/finalize 不收敛 node；scan_terminal_drift 缺 node | 终态不变量 + Gate 全层检查 |
| SI3-008 | P1 | OPEN | is_test_fixture=1 客户可保持 operational；客户/问卷列表零过滤 | before_audit cust=1；R7/R17 红 | create_customer 不联动 scope；list 无过滤 | 结构性 fixture + 默认 operational 列表 |
| SI3-009 | P1 | OPEN | 父子一致性不校验 customer/project；客户端可自证 | R11 红 | check_child 只比 scope/test_run | 六维校验 |
| SI3-010 | P1 | OPEN | UAT V4 report ids={} 且 validator 放行 | uatv4/report.json；R16 红 | _validate_uatv4 不查 ids；driver 未写 ids | ids 必填 + validator fail-closed（UAT V5 重建） |
| SI3-011 | P1 | OPEN | Scope Registry 缺失（仅 20+ 表白名单，120+ 表未登记） | sqlite_master vs _SCOPED_TABLES | SI2 只登记域表 | 全表 Registry + Gate 覆盖率检查 |
| SI3-012 | P2 | OPEN | UI：测试数据默认勾选/favicon 404/Agent 浮层遮挡/model 命名混淆等 12 项 | 指令第七节 | 前端遗留 | UI 修复批次 |

（T1 起每个红测试对应一个 Issue；新 Bug 追加 SI3-013+。）

# ISSUES · Scope Integrity V3

> 格式：`| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |`

| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |
|---|---|---|---|---|---|---|
| SI3-001 | P0 | CLOSED | 隔离只看行自身列，父链 effective scope 泄漏全部漏检（media=24/work=8/recognition=5/usage=89） | .eval/scope_v3/before/before_audit.json；R1/R2/R3/R6/R15 红 | OPERATIONAL_FILTER 不追父链；operational_leakage 只查自身列 | Scope Graph V3：ScopedQuery 父链边扫描 + usage_api/analytics/home 全量 effective 口径；回填后审计归零（after_audit_final.json） |
| SI3-002 | P0 | CLOSED | Gate 2.1 假阳性 READY（scanner except/continue + 静态 JSON + 无 freshness） | gate.json READY vs 审计计数；R13/R14 红 | gate_evaluator 吞异常；control/gate 只读文件 | Gate 3.0：fail-fast scanner + db_fingerprint 绑定 + /control/gate 实时 freshness 复评（UAT V5 注入负例 STALE→修复→恢复） |
| SI3-003 | P0 | CLOSED | test_run_id 无 registry 校验；INSERT OR REPLACE 覆盖 namespace；先 commit 再 bind | R9/R10/R12 红 | resolver 不查 uat_test_run_v1；test_data.py 写法 | assert_test_run_current（存在/current/客户匹配）；namespace 幂等仅内容一致否则 409；create_scoped_customer 同事务 + 各受信端点前置校验 |
| SI3-004 | P0 | CLOSED | Agent 工具创建 BI/问卷/识别对象不透传 scope（BI draft 5+ 条 operational） | before_audit bi=5/11；R4 红 | runtime._exec_tool 不带 ctx | _exec_tool(scope=ctx)；analytics/workflow/识别创建同事务写 scope；answer_anomaly 新版本继承 scope（browser 证据抓出的二次泄漏） |
| SI3-005 | P0 | CLOSED | 失败 Agent 路径吞 scope 异常，账本落 operational（5 轮） | before_audit failed_agent=5；R5 红 | _record_definition_failure 的 resolve except 兜底 operational | 失败路径先解析 scope；Work/Usage/Evidence 同 scope；历史 5 轮经 r16 回填归档 |
| SI3-006 | P0 | CLOSED | Usage/财务 API 与汇总零 scope 过滤（89 条 fixture 计入运营） | before_audit usage=89/invoice=2；R6 红 | usage_api/finance 无 effective 口径 | _EFFECTIVE_OP（自身列⊕attribution⊕父 run⊕父客户）；billing 排除 attributed fixture；不可变行经 attribution ledger（96+5 条，原行未动） |
| SI3-007 | P1 | CLOSED | terminal Run 下 node 未收敛（39 条）；Gate 不查 node 层 | before_audit node=39；R8 红 | cancel/finalize 不收敛 node；scan_terminal_drift 缺 node | finalize_run/retry_run 收敛 node（含 waiting_* 全状态）；scan_terminal_drift 加 node_open；r10 历史收敛 39 条 |
| SI3-008 | P1 | CLOSED | is_test_fixture=1 客户可保持 operational；客户/问卷列表零过滤 | before_audit cust=1；R7/R17 红 | create_customer 不联动 scope；list 无过滤 | create_customer fail-closed（无 test_run 拒绝 409）；list_customers/list_surveys/list_reports/duplicates 默认 operational；前端搜索/分页/scope 筛选 |
| SI3-009 | P1 | CLOSED | 父子一致性不校验 customer/project；客户端可自证 | R11 红 | check_child 只比 scope/test_run | 六维校验（tenant/customer/project/scope/test_run/correlation）；parent_child_mismatch 加 customer/test_run 维度 |
| SI3-010 | P1 | CLOSED | UAT V4 report ids={} 且 validator 放行 | uatv4/report.json；R16 红 | _validate_uatv4 不查 ids；driver 未写 ids | REQUIRED_UAT_IDS（22 键）fail-closed；UAT V5 driver 全链收集 24/24（report.json ids 无空） |
| SI3-011 | P1 | CLOSED | Scope Registry 缺失（仅 20+ 表白名单，120+ 表未登记） | sqlite_master vs _SCOPED_TABLES | SI2 只登记域表 | scope_registry.py 123/123 表分类登记（七类）+ Gate scope_registry_full 检查（fail-fast，未登记即 BLOCKED_BY_SCOPE_REGISTRY） |
| SI3-012 | P2 | CLOSED | UI 12 项（测试默认勾选/favicon/浮层/命名/Gate 首屏/视口等） | 指令第七节；browser_evidence 12/12 | 前端遗留 | T9 批次全部修复：favicon 200、测试勾选默认关+test_run 必填提示、识别页 V4 Best 生产横幅+冻结映射+模型分组、SystemStatus Gate 首屏、首页错误码进详情、客户/问卷搜索分页、窄视口表格横向滚动、Agent 抽屉响应式；四视口无溢出、console unexplained=0 |

（新 Bug 追加 SI3-013+。截至 FINAL-REPORT 无新增。）

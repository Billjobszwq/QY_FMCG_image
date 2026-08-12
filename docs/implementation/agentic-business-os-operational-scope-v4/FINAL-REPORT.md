# FINAL-REPORT · Operational Scope V4（按指令第十九节 47 项顺序）

## 1. HEAD/branch/worktree
- branch `feat/nextgen-training-cycle-v2`；开工基线 HEAD `eb19425f`
  （V3 收尾）；本轮开工实际 HEAD `63679be0`（含外部 TaaS commits）。
- 收尾 HEAD：本轮最后一个提交（见 EXECUTION-LOG；`git log` 实时可查）。
- worktree：tracked 干净（`git status --porcelain -uno` = 空）。

## 2. 开工期间检测到的外部 commit
`2b22b519`/`4bb0d49f`（TaaS 规格与计划文档）、`805fc796`/`cff57e1c`/
`63679be0`（TaaS 奶油色主题与推广页）。diff 审计：仅 docs/promotion、
tests/promotion、推广 HTML，不触碰 scope 链/平台代码；已纳入基线。

## 3. 本轮 commit 链
`6121353f`(T0 审计+治理+Gate 降级) → `fe7a543c`(T1 红测试 15 项) →
`9fd80c7c`(T2–T5 IAM 生命周期/BI effective/Gate 3.1/Registry 语义/
前端默认值) → `705024ec`(T5-live 收敛审计证据) → `f83aeb99`(审计口径)
→ `b1dded1c`(T7 UAT V6 57/57) → `a4fb3f7f`(T6/T8 浏览器 30/30 +
浮层/IAM 列表) → 收尾文档提交。

## 4. 完整阅读清单
READING-LIST.md 26 项（全局 routing、CODEX handbook、USER-HANDBOOK、
OPERATOR-RUNBOOK、MODULE-AGENT-DEV-GUIDE、SI2/SI3 治理目录、
scope_v3 gate/uatv5/browser 证据、QA 报告、scope/scope_registry/
test_data/gate_evaluator/home_center、IAM/BI/Finance/Usage/Workflow/
Agent/Command Gateway 代码、Web IAM/BI/Finance/SystemStatus/AppShell/
Supervisor 浮层、40+ commits、schema 001–058、服务/CURRENT/未跟踪资产）。

## 5. before 红测试结果
`tests/platform/test_si4_operational_surface.py` 15/15 全红
（.eval/scope_v4/before/）：IAM 身份生命周期 5 项、BI effective 3 项、
前端默认值 1 项、Registry 语义 2 项、Gate 3.1 4 项。

## 6. 数据库备份路径与 sha256
`.platform/backups/platform_pre_scope_v4_20260813T023659.sqlite`
sha256=`e886123f96bab1944d846b5d651ae11268932e646f9dc08c8931bb885bb328b1`
（SQLite backup API；源与备份双向 integrity=ok）。

## 7. active UAT principal 前后数量
before **85** → after **0**（r20/r21：registry 回绑 provenance +
disabled+history；历史行保留）。

## 8. UAT membership 前后数量
before **97**（全带客户授权）→ after operational **0**（97 条
visibility=history；审计入账 r21_membership_convergence_fix）。

## 9. archived UAT 登录负例
UAT V6 `post_archive_login_rejected`：**6/6 拒绝**；拒绝码
`IDENTITY_ARCHIVED`（401，写 iam_audit_event_v1）；会话全部失效。

## 10. IAM 生命周期设计
02-IAM-TEST-IDENTITY-LIFECYCLE.md：迁移 057 provenance 列
（data_scope/test_run_id/origin/visibility/archived_at/
disabled_reason）；创建即登记（受信 test_run fail-closed）；grant
继承；归档同事务收敛（principal 禁用/membership 归档/session 失效）；
登录/授权/列表/统计统一消费 provenance 列（唯一事实源，运行时禁名称）。

## 11. IAM 页面/API 对账
运营 `/iam/principals` fixture=0；`include_fixture=true` 可见全历史；
页面新增搜索/状态筛选/分页（P2-002）；浏览器断言
active_uat_identities=0、iam_fixture_token_count=0。

## 12. UAT metric 前后数量
before 运营口径 **8** → after **0**（r22 归档 + 迁移 058 生命周期列；
运营指标目录 list_metrics 默认排除 fixture/archived）。

## 13. BI dashboard/report/anomaly 前后数量
- dashboard：运营 **9 → 0**（r23；含 uat-cust-a demo 看板）
- report：运营 UAT 名/客户 **1+ → 0**（r23；版本链继承 SI3 r15）
- anomaly：operational 中 UAT 链 0（SI3 已收敛，UAT V6 复验）

## 14. BI data-product 前后对账
before：物理 37/25/22/25/50/195/24/20；after：data-products 端点 =
运营 Domain API 逐项一致（当前运营客户 0 → customers=0；UAT V6 期间
`data_products_reconciled` 断言 dp==api 通过）。

## 15. operational customer/API/BI 一致性
`bi_effective_counts` 唯一口径（analytics.py），data-products 端点与
Gate 3.1 `data_products_effective_basis` 共用；三处一致。

## 16. BI 默认客户修复
BIWorkbench `useState("uat-cust-a")` → `useOperationalCustomer`
（唯一运营客户预选/无客户空态/多客户人工选择）；浏览器断言
bi_default_customer_clean=CLEAN。

## 17. Finance 默认客户修复
Finance/Geo/Usage 共 6 处 `demo-cust-a`/`uat-cust-a` →
CustomerPicker；浏览器断言 finance_default_customer_clean=CLEAN；
源码静态扫描 fixture 默认值 7 → 0。

## 18. Usage effective scope 对账
`_EFFECTIVE_OP`（自身列⊕attribution⊕父 run⊕父客户）；UAT V6
`operational_usage_excludes_fixture` 通过；fixture usage 195 条全部
attribution 绑定，运营汇总 0 计入。

## 19. invoice fixture 排除证据
`generate_invoice` 三重过滤（u.data_scope/r.data_scope/attribution）
+ invoice 继承客户 provenance（迁移 055 列）；UAT V6
`finance_fixture_dry_run_isolated`：fixture 客户账单 total=0.0。

## 20. Scope Registry 语义覆盖率
123/123 表 = 100%（物理）+ 每表 7 项生命周期声明
（uat_creatable/provenance/archive_rule/login_impact/billing_impact/
bi_impact/browser_surface）；Gate `scope_registry_full` fail-closed。

## 21. global/reference 类型防逃逸规则
_DEFAULT_LIFECYCLE_BY_CATEGORY 对 global_configuration/reference_registry
强制 "restricted + provenance 可追踪 + UAT 创建可归档且不参与运营执行"；
敏感表（iam_principal/membership/auth_sessions/bi_metric/bi_dashboard/
import_batch/fin_rate_card/agent_definition/platform_flag）有专项声明。

## 22. Gate 3.1 新增检查
iam_active_fixture_principal_zero、iam_operational_fixture_membership_zero、
uat_metric_operational_zero、uat_metric_archived_consistent、
uat_dashboard_operational_zero、data_products_effective_basis、
browser_routes_covered（12 页强制）、BLOCKED_BY_IAM_IDENTITY/
BI_EFFECTIVE/FINANCE_CONTEXT/OPERATIONAL_FIXTURE_SURFACE 状态。

## 23. Gate 负例结果
`.eval/scope_v4/gate_negative_tests.json`：**22 项全部有阻断证据**
（red→green / live 负例 / browser 断言）。

## 24. UAT V6 namespace
`uatv6_<UTC>_<随机>`（以 `.eval/scope_v4/uatv6/report.json` 为准；
先建 Test Run 上下文，全部对象携带/继承 test_run_id）。

## 25. UAT V6 principal/membership IDs
report.ids.principals（6 个 pr-* ID）、ids.memberships=count=7。

## 26. UAT V6 BI IDs
ids.metric、ids.dashboard、ids.bi_report、ids.anomaly（全部非空）。

## 27. UAT V6 Finance IDs
ids.finance_dry_run_invoice（invoice ID）、ids.rate_calc=rc_standard。

## 28. UAT V6 全部业务 IDs
ids 共 **30 键全部非空**（test_run/customer/project/sku/employee/
address/field_task/route/geofence/travel/survey/assignment/response/
media/workflow_def/run/work/agent_run/agent_failed_run/bi_report/
anomaly/recognition_task/evidence/usage/principals/memberships/
metric/dashboard/finance_dry_run_invoice/rate_calc）。

## 29. UAT V6 结果
**57/57 通过**（validator problems=[]）；含归档后登录拒绝 6/6、
IAM 页干净、历史保留、泄漏注入 freshness 闭环。

## 30. Test Run 归档结果
uatv6 namespace status=archived；全 Domain 泄漏=0；test_run 完整率
100%；父子一致 0 冲突；测试中心全历史可查。

## 31. 正常首页 fixture 检查
home_fixture_token_count=0（浏览器真实文本断言）。

## 32. IAM 页面 fixture 检查
iam_fixture_token_count=0 + active_uat_identities=0。

## 33. BI 页面 fixture 检查
analytics_fixture_token_count=0 + bi_default_customer_clean=CLEAN。

## 34. Finance 页面 fixture 检查
finance_fixture_token_count=0 + finance_default_customer_clean=CLEAN。

## 35. 12 个一级模块浏览器验收
home/data-import/survey-design/geo-addresses/vision-recognize/
analytics-reports/workflow-studio/iam-accounts/master-customers/
finance-contracts/help/status —— 12/12 fixture token=0，共 30 项
断言 30 通过（.eval/scope_v4/browser/）。

## 36. 四视口截图
1440（12 页）+ 1280/1024/768（home/status/analytics/iam），
si4_*.png 28 张；全部无横向溢出（双采样）。

## 37. 主管 Agent 浮层验收
窄屏缩小（1024:34px/768:30px）+ 安全边距 + opacity；aria-label/键盘
聚焦保留；四视口 overflow 断言通过（P2-001 CLOSED）。

## 38. Console/network 结果
console_errors_unexplained=**0**（登录后清空再逐页收集）。

## 39. API 性能
延续 SI3 实测（本轮未回退）：最差 home/dashboard p95=28.2ms；
control/gate freshness p95=8.6ms（<100ms 预算）；首页加载
p95=186ms <2s。

## 40. Web bundle
初始 gzip ≈72KB 保持；echarts 381+177KB 两 chunk <500KB；唯一
warning = maplibre 单库 949KB raw/249KB gzip（仅 Geo 路由懒加载，
预算 gzip≤260KB；未调 warningLimit）。

## 41. Hermetic 测试
**1447 passed, 1 skipped, 6 deselected, 0 failed**（基线 1425 +
si4 15 + 外部 promotion 测试；.eval/scope_v4/test_report.json）。

## 42. Host MPS
**6 passed**（`pytest -m host_mps`）。

## 43. TypeScript/build/diff-check
`npx tsc --noEmit` 干净；`npm run build` 成功；`git diff --check`
干净；scope.py 无尾随空格。

## 44. SQLite integrity/migrations
`PRAGMA integrity_check`=ok（回填前后多次）；迁移 057（IAM
lifecycle）/058（BI/import lifecycle）应用；篡改校验链完整（058 条）。

## 45. 服务/重启恢复
8091/8092/8300/8400 全程可用；每次重启为 graceful（bin/abos
restart），重启后 `abos status` 验证四服务 UP 与迁移应用。

## 46. 当前 production 声明
`.models/bundles/CURRENT.json` 始终 `prod_v4_best_r1`；本轮未执行
任何 bundle 切换。

## 47. 未启动训练声明 + 未 merge/push/deploy 声明 + 未关闭问题
- 未启动任何 YOLO/SAM/Classifier/QLoRA/长训练（abos status
  训练进程=0）。
- 未 merge、未 push、未 deploy。
- 未关闭问题：无（SI4-001…011 全 CLOSED；无新增）。
- 诚实残留：地理编码/瓦片未配 Key（degraded，历史遗留，与 scope
  契约无关）；真实数据 UAT 与人工验收仍由用户执行。

---

## 最终机器 Gate
`.eval/scope_v4/gate.json` = **READY_FOR_REAL_DATA_UAT**（34 检查
0 失败；HEAD/代码树/迁移/DB fingerprint 绑定；/control/gate 实时
freshness 复评确认）。该结论由机器评估产生，非手写。

## 用户真正需要执行的下一步
1. 用真实客户/地址/问卷数据执行真实数据 UAT（系统侧 IAM/BI/Finance
   隔离与 Gate 3.1 已全部机器证明）；
2. 人工走查（建议：首页→客户库→IAM→BI→财务→系统状态 Gate 区块）；
3. 测试历史在"系统状态→测试与证据中心"按 Test Run 审计；
4. 是否 merge/push 由用户决定，本轮未执行。

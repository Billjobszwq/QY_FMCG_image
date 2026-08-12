# FINAL-REPORT · Scope Integrity V3（按指令第十四节顺序）

## 1. HEAD / branch / worktree

- branch：`feat/nextgen-training-cycle-v2`
- 开工基线 HEAD：`eb19425f`（与指令一致）
- 收尾 HEAD：本轮最后一个提交（见 EXECUTION-LOG 提交链；
  `git log --oneline -10` 实时可查）
- worktree：tracked 干净（`git status --porcelain -uno` 空）；
  未跟踪资产（.datasets_nextgen/.micro_gold_*/.sam_* 等）零触碰。

## 2. commits

- `6b5ea854` si3(T0)：独立审计 + 17 红测试 + 备份 + Gate 降级 + 文档
- `003271e7` si3(T1,T2,T6-pre)：Scope Graph V3 核心 + 创建路径透传
- `de3b6923` si3(T8-prep)：fail-closed 受信创建 + UAT V5 driver
- `13abb465` si3(T9,T10)：UI 批次 + chunk 拆分
- `18215671` si3(T8-prep 补强)：fence/validator/回填 r14
- `cb5a11cb` si3(T8)：UAT V5 48/48 + Gate 3.0 + 迁移 055/056
- `bb6802ef` si3(T9-fix)：浏览器证据 12/12 + 版本链泄漏修复 + r15–r18
- 收尾文档提交（本文件所在提交）

## 3. 完整阅读清单

- 全局 GLOBAL_AGENT_ROUTING.md（~/.local/share/ai-workflow/routing/）
- 项目根无 AGENTS.md / 项目级 GLOBAL_AGENT_ROUTING.md（find 验证，
  以全局 routing 为准）
- docs/CODEX-PROJECT-HANDBOOK.md、USER-HANDBOOK.md、
  OPERATOR-RUNBOOK.md、MODULE-AGENT-DEV-GUIDE.md
- docs/implementation/agentic-business-os-uat-scope-isolation-v2/ 全 13 件
- .eval/uat_scope_v2/{gate.json, uatv4/report.json,
  browser/browser_evidence.json}
- src/platform/{scope,test_data,gate_evaluator,home_center,survey,
  analytics,finance,iam,workflow,control_plane}.py、
  api/{usage_api,iam_api,geo_api,survey_api,workflow_api,
  analytics_api,control_plane_api}.py、agents/runtime.py、
  data/store.py、modules/training_control/profiles.py
- 最近 35 个 commit。

## 4. before 复现数据

`.eval/scope_v3/before/before_audit.json`（独立 SQL 审计器，只读）：

| 指令项 | 实测 | 基线 |
|---|---|---|
| media 泄漏 | 24 | ≈24 ✓ |
| work 泄漏 | 8 | ≈8 ✓ |
| recognition 泄漏 | 5 | ≈5 ✓ |
| BI draft 泄漏 | 5（严格因果）/11（时间窗） | ≈5 ✓ |
| 失败 Agent operational | 5 | ≈5 ✓ |
| Usage 泄漏 | 89 | ≈80 ✓ |
| is_test_fixture 客户 operational | 1 | ≈1 ✓ |
| terminal Run 下 non-terminal node | 39 | ≈39 ✓ |
| UAT V4 report ids | {}（0） | 空 ✓ |

红测试 17/17 全红（.eval/scope_v3/before/t1_red_results.txt），
覆盖指令三.9–20 与第四节契约。

## 5. 数据库备份与 hash

- `platform_pre_scope_v3_20260812T224724.sqlite`
  sha256=`753a809362bd9b54979ce2e38d2d9c9d5e8b8d2196ff2a4f02b321ad671d15e4`
- `platform_pre_backfill_v3_20260812T233822.sqlite`
  sha256=`f42cebe01af2c67b12930797cd00817a0f069a1aea3620e48d0cc12ccb0e26f6`
- 均用 SQLite backup API；源与备份双向 `integrity_check`=ok。

## 6. 新 Scope Graph

01-SCOPE-GRAPH-CONTRACT.md：唯一 ExecutionContext（tenant/customer/
project/data_scope/test_run/correlation/parent_run/actor/source/
definition-artifact-version）；解析顺序 Test Run registry → 父 Run
→ response/assignment 父链 → Customer → operational；六维父子校验；
同事务写入；namespace 不可覆盖；失败路径先解析 scope。

## 7. 全表 Scope Registry 与覆盖率

`src/platform/scope_registry.py`：123/123 表（100.0%），七类
（scoped_business_object / immutable_ledger / global_configuration /
reference_registry / derived_projection / cache_runtime / audit_only），
每表含主键/scope 列或推导路径/父边/查询与归档规则。Gate 检查
`scope_registry_full` fail-closed（缺表 → BLOCKED_BY_SCOPE_REGISTRY）。

## 8. 每个 P0/P1 根因

见 ISSUES.md SI3-001…SI3-012（全部 CLOSED）：核心假阳性根因 =
隔离只看行自身列 + scanner 吞异常 + 静态 Gate；次生根因 = 创建路径
不透传 scope（media/BI/识别/失败账本/报表版本链）、终态不收敛 node、
test_run 无 registry 校验、namespace 可覆盖、先 commit 再 bind。

## 9. 红测试→修复→绿测试证据

- 红：.eval/scope_v3/before/t1_red_results.txt（17 failed）
- 绿：hermetic 1425 passed（含 17 项 si3 全绿），
  .eval/scope_v3/test_report.json
- 中间证据：UAT V5 预演逐轮修复记录（EXECUTION-LOG）。

## 10. 历史回填数量与审计

`scripts/scope_backfill_v3.py` r0–r18（多轮幂等 --apply）：
- 结构性修正：work 17+、media 24、recognition 5、BI 11(+版本链 4)、
  agent_run 10、customers 1、projects/geo/survey 若干、node 12+39、
  runs(客户链) 5、legacy sku 11
- 不可变账本 attribution：usage 96+5、evidence 65+5（原行零改动）
- 审计：`scope_backfill_audit_v1`（规则/父对象/数量/ids_hash/actor/
  时间）+ `scope_attribution_ledger_v1`；
  `.eval/scope_v3/backfill_report_apply.json`

## 11. media/work/recognition/BI/Agent/Usage 前后计数

| 口径 | before | after |
|---|---|---|
| media 泄漏 | 24 | 0 |
| work 泄漏 | 8 | 0 |
| recognition 泄漏 | 5 | 0 |
| BI 泄漏 | 5/11 | 0 |
| 失败 Agent 泄漏 | 5 | 0 |
| Usage 泄漏 | 89 | 0（effective 口径） |
| fixture 客户 operational | 1 | 0 |
| node 漂移 | 39 | 0 |

证据：.eval/scope_v3/after_audit_final.json（全部为 0，integrity ok）。

## 12. 首页及各列表隔离前后

- before：首页日历/最近对象含 UAT 工作流 40/46、BI 10/20、fixture
  项目 14/14；客户/问卷/报表列表零过滤（00-LIVE-AUDIT §5）
- after：浏览器真实文本断言 home/customers/survey/vision fixture
  token=0（browser_evidence.json）；home dashboard API 复扫 0；
  列表默认 operational，fixture 仅测试与证据中心可见（含 test_run/
  状态/数量/归档时间）。

## 13. WorkItem/Node/Timer/Branch 终态对账

- finalize_run/retry_run 收敛 node（含 waiting_timer/
  waiting_approval/waiting_human 全状态）；approval 子待办随主 Run；
  retry 旧 running 节点先收敛
- scan_terminal_drift 扩展 node_open；历史 39 条已收敛；
  UAT V5 后 drift=0。

## 14. Usage/财务隔离

- usage_api summary/rows/export/budgets 全走 _EFFECTIVE_OP
  （自身列⊕attribution⊕父 run⊕父客户）
- generate_invoice 排除 attributed fixture usage
- 运营口径 fixture=0；下钻链（run/evidence）保留（UAT V5 断言）。

## 15. Gate 3.0 freshness 机制

- db_fingerprint：scope-graph 聚合 sha + event 水位 + outbox pending
  + work 投影 hash + 关键表计数（先重建投影再取计数，避免假 STALE）
- gate.json 绑定 HEAD/代码树/migration/db_fingerprint；
  GET /api/v1/control/gate 每次实时复评（p95=8.6ms），任一绑定变化
  → STALE_GATE_EVIDENCE，绝不返回旧 READY。

## 16. Gate 全部负例结果

.eval/scope_v3/gate_negative_tests.json：14 项（≥12 要求）——媒体/
Work/识别/BI/Agent 失败/Usage 泄漏、节点漂移、静态 Gate 失效
（live 注入：BLOCKED→STALE→修复→恢复）、未知表、异常被吞、
客户/project 冲突、archived test_run、报告 ids、列表隔离。
修复前全部可泄漏（红测试证据），修复后全部阻断。

## 17. UAT V5 namespace

`uatv5_20260813003451_*`（最终一轮，report.json 为准；此前迭代
namespace 均已结构化归档）。Test Run 上下文先建；全部对象携带或
继承 test_run_id；归档后 status=archived。

## 18. UAT V5 全部对象 ID

.eval/scope_v3/uatv5/report.json `ids`：24/24 非空
（test_run/customer/project/sku/employee/address/field_task/route/
geofence/travel/survey/assignment/response/media/workflow_def/run/
work/agent_run/agent_failed_run/bi_report/anomaly/recognition_task/
evidence/usage）。

## 19. UAT V5 全领域链结果

48/48 通过：六角色+跨客户 403；问卷全题型+跳题 DAG+自动评分+
门头负例→正例；主工作流 10 节点类型（trigger/transform/condition/
wait/parallel/join/loop/approval/agent/command）succeeded；Agent BI
草稿 fixture-scoped；异常→追问→人工回答→报表 v2；差旅派生；
归档后全 Domain 泄漏=0、中心保留历史；validator problems=[]。

## 20. Browser 四视口截图

.eval/scope_v3/browser/：si3_home/status_{1440,1280,1024,768}.png +
customers/survey/vision@1440；12/12 断言通过（含四视口无横向溢出
双采样）。

## 21. console/network 结果

console_errors_unexplained=0（登录后清空再逐页收集）；favicon
GET=200（修复 404）。

## 22. 性能和 bundle 结果

- API（30 采样）：home/dashboard p50=27.0/p95=28.2ms；
  control/gate p95=8.6ms；其余 ≤1.4ms（api_perf.json）
- 首页加载 p95=186ms <2s（home_load_perf.json，CDP ×10）
- bundle：初始 index 63KB(gzip 18KB)+vendor-react 165KB(gzip 54KB)
  ≈72KB gzip 保持；BI echarts 模块化 1134KB→381+177KB 两 chunk
  均<500KB；唯一 >500KB warning = vendor-maplibre 949KB raw/249KB
  gzip——**实测理由**：maplibre-gl 为单一不可拆库，仅 Geo 路由懒
  加载；**加载预算**：gzip ≤260KB、仅 /geo 路由触发、首屏不加载。
  未调高 chunkSizeWarningLimit。

## 23. hermetic 测试

1425 passed, 1 skipped, 6 deselected（基线 1408 + 新增 17；0 失败），
.eval/scope_v3/test_report.json。

## 24. host MPS 测试

`pytest -m host_mps`：6 passed。

## 25. typecheck/build/diff-check

- `npx tsc --noEmit`：干净
- `npm run build`：成功（warning 仅 maplibre，理由见 §22）
- `git diff --check`：干净；scope.py 无尾随空格。

## 26. SQLite integrity/migrations

- `PRAGMA integrity_check`=ok（回填前后、UAT 后多次复验）
- 新增迁移 054（attribution ledger）/055（finance scope 列）/
  056（geofence scope 列），幂等应用，篡改校验链完整。

## 27. 服务和恢复

8091/8092/8300/8400 全程 UP；仅 graceful `bin/abos restart`
（每次重启后 `abos status` 验证四服务恢复与迁移应用）。

## 28. production 未切换声明

`.models/bundles/CURRENT.json` 始终为 `prod_v4_best_r1`；未执行
任何 bundle 切换。

## 29. 未启动训练声明

全程未启动任何 YOLO/SAM/Classifier/QLoRA 训练；`abos status`
训练进程=0。

## 30. 未关闭问题

无（ISSUES SI3-001…012 全 CLOSED）。诚实残留：地理编码/瓦片未配
Key（degraded，历史遗留，不影响 scope 契约）；真实数据 UAT 与人工
验收仍待用户执行。

## 31. 最终机器 Gate

`.eval/scope_v3/gate.json`（si3_gate_evaluate.py 全量评估，见
/control/gate 实时结果）。评估输入：live store 扫描（泄漏/registry/
终态/上下文）+ HEAD/树/migration 绑定 + ISSUES 账本（0 OPEN P0/P1）
+ UAT V5 报告（validator clean）+ 浏览器证据（12/12）+ 测试报告
（0 failed）+ 服务健康 + CURRENT 校验 + 无训练。

## 32. 用户真正需要执行的下一步

1. 用真实客户/地址/问卷数据执行真实数据 UAT（系统侧已就绪：
   fixture 隔离、Usage 计费隔离、Gate freshness 均已机器证明）；
2. 人工验收 UI（建议从 首页 → 客户库 → 问卷 → 识别 → 系统状态
   Gate 区块走查）；
3. 如需查看测试历史：系统状态页"测试与证据中心"（全部 UAT
   namespace 可审计、不可删）；
4. 本轮未 merge/push/deploy；是否推进由用户决定。

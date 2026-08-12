# ISSUES · UAT Scope Isolation V2

> 格式：`| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |`

| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |
|---|---|---|---|---|---|---|
| SI2-001 | P0 | CLOSED | Fixture 只退出了 WorkItem，没有退出完整业务系统 | 00-LIVE-AUDIT §4.1/§5：field=14/14、survey=14/15、project=14/14、calendar=3/5、workflow=40/46、BI=10/20 均无 data_scope 列且进首页 | TestDataService 只处理 3 表；home_center 无 scope 过滤 | 迁移 051 全表 scope 列 + backfill + 首页/Agent/BI/财务默认 operational（test_si2 22/22 绿；live scan leakage={}） |
| SI2-002 | P0 | CLOSED | 真实数据 UAT 会与历史 fixture 混合 | 同 SI2-001 | 全 Domain 无统一 ExecutionScope | ExecutionScopeV1 单一事实源 + UAT V4 31/31（归档后泄漏=0） |
| SI2-003 | P1 | CLOSED | test_run_id 未贯穿新创建对象 | business_run fixture 79 条 test_run_id=0；mark_namespace 提前调用、后续对象不继承 | 创建路径无 scope 解析/继承 | ScopeResolver 贯穿 gateway/workflow/agent；live 79/79 补齐；UAT V4 完整率 100% |
| SI2-004 | P1 | CLOSED | 归档依赖名称前缀 | test_data.py archive_namespace `customer_id LIKE namespace%` | 无结构化 scope | archive_namespace 按 test_run_id 结构化（test_16/17 绿） |
| SI2-005 | P1 | CLOSED | 浏览器 Gate 只验证截图存在 | gate_evaluator.py browser 检查仅 files+console | 无语义断言 | Gate 2.1 browser_semantic_assertions + si2_browser_evidence.py（pages[] expected/actual） |
| SI2-006 | P1 | CLOSED | Gate 不绑定当前代码状态 | 旧 gate source_commit=6664022f vs HEAD=9f3554e7 | 无 HEAD/树 hash 绑定 | Gate 2.1 HEAD/代码树 hash 绑定 + STALE_GATE_EVIDENCE（test_19/20 绿） |
| SI2-007 | P2 | CLOSED | Gate residue evidence 显示 None | .eval/v3_uat_v3/gate.json evidence="None" | falsy/or 逻辑 | 显式 int()（test_21 绿） |
| SI2-008 | P2 | CLOSED | 前端初始包过大 | web/dist/index-*.js=2.69MB | 单 bundle 无 lazy | 路由级 lazy：初始 gzip 818KB→72KB；重型 chunk 异步并披露（BIWorkbench gzip 382KB=echarts 全量、Geo 255KB=maplibre，无法再拆故异步加载） |
| SI2-009 | P2 | CLOSED | TestDataService pytest collection warning | pytest collect warning PytestCollectionWarning | 类名以 Test 开头 | FixtureTestDataService + __test__=False + 别名（test_22 绿） |
| SI2-010 | P2 | CLOSED | survey 提交对非 dict 包裹答案 500（AttributeError） | UAT V4 首跑 app.log：survey.py _score inputs 推导 | _score 假定答案均为 {"value":...} | survey.py 兼容非 dict 答案（已修） |

（T1 起每个红测试对应一个 Issue；新 Bug 追加 SI2-010+。）

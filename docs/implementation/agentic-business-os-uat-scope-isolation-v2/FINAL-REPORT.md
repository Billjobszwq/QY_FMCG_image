# FINAL-REPORT · UAT Scope Isolation V2

> 按指令第十节 57 项顺序汇报；每项通过均附证据路径/命令。

1. HEAD/branch/worktree：开始 `9f3554e7` / `feat/nextgen-training-cycle-v2` /
   tracked 干净；结束 HEAD 见 `git log -1`（本轮提交链见第 3 项），
   tracked worktree 在终评前提交干净（Gate `tracked_worktree_clean`）。
2. 开始和结束 commit：`9f3554e7` → 最后代码提交 `ea6ea086`；终评
    gate.json source_commit = 终评时 HEAD（其后仅治理文档提交）。
3. 本轮 commit 链：`18ac09d0`(T0) → `5183cd83`(T1 红) → `013efe3a`(T2-T4/T6)
   → `9548cc30`(T3 backfill) → `52b9069b`(T5/T8-prep) → `fbeac0f3`(T8)
   → `b38d9421`(T9) → `ea6ea086`(T6/T7/T10 收尾；其后仅治理文档
   小步提交与 Gate 终评)。
4. 完整阅读文件清单：READING-LIST.md（23 项；其中 AGENTS.md 与
   docs/implementation/agentic-business-os-v3/ 现场不存在，如实记录）。
5. 初始服务/DB/模型/训练进程：00-LIVE-AUDIT §2-§4（四服务 UP、
   integrity ok、50 migrations、prod_v4_best_r1、训练进程 0）。
6. Before fixture 污染统计：00-LIVE-AUDIT §4.1（field 14/14、
   survey 14/15、project 14/14、calendar 3/5、wf 40/46、BI 10/20、
   fixture runs test_run_id 0/79）。
7. Before 首页/工作流截图：SQL 证据固化于 00-LIVE-AUDIT §5；
   before 截图未单独采集（如实声明；after 截图在
   .eval/uat_scope_v2/browser/）。
8. P0/P1/P2 Issue 清单：ISSUES.md SI2-001..010。
9. 每个问题的复现证据：ISSUES.md"复现证据"列 + 00-LIVE-AUDIT。
10. 每个问题的根因：ISSUES.md"根因"列。
11. 红测试数量和首跑结果：22 项，首跑全红
    （.eval/uat_scope_v2/t1_red_results.txt：collection error
    ModuleNotFoundError src.platform.scope），最终 22/22 绿。
12. ExecutionScopeV1 最终结构：src/platform/scope.py（tenant/customer/
    project/data_scope/test_run_id/correlation/parent_run/actor/source/
    created_at；data_scope ∈ operational/uat_fixture/demo_fixture/
    system/archived）。
13. 唯一事实源设计：DEC-SI2-001 = 业务表统一 scope 字段（方案 A）；
    object_scope_binding_v1 为只读派生视图（迁移 051）。
14. 数据库迁移编号：051_execution_scope_v1、052_execution_scope_geo_v1、
    053_execution_scope_customer_v1。
15. 迁移备份路径和 hash：.platform/backups/
    platform_pre_scope_v2_20260812202343.sqlite，
    sha256=7d65b1ced2ddefd2fa2cbad77aac9986c5e416ad7edddde1ce904551e783a41c，
    integrity ok。
16. SQLite integrity：ok（迁移前后与 T10 复验；gate
    `sqlite_integrity`）。
17. Legacy backfill 数量：runs 79、projects 14、field 14、assignments 14、
    responses 15、calendar 3、node 执行 161、timer 15、branch 20、
    recognition 22、agent_run 37、wf 定义 40、BI 10、问卷定义 10、
    fixture 客户 20；全部入 scope_backfill_audit_v1 账本。
18. unresolved/quarantine 数量：0（无需人工裁决对象；
    center.unresolved=0）。
19. 27 个旧 UAT V3 Run 的 test_run_id 修复：本机库 UAT V3 时代 fixture
    runs 共 79 条（含 V2/V3 多轮），全部补齐（缺失 0；
    gate `fixture_test_run_id_full` evidence="0"）。
20. 全 Domain scope coverage matrix：02-DOMAIN-SCOPE-MATRIX.md。
21. Workflow scope 继承证据：start_run ScopeResolver（test
    test_11/12）；UAT V4 `workflow_run_scope_inherited`
    （data_scope=uat_fixture, test_run_id=namespace）。
22. Agent scope 继承证据：test_10；UAT V4 `agent_invoke_scoped`；
    失败账本同样继承（_record_definition_failure + test）。
23. Recognition/Evidence/Usage 继承证据：CommandGateway submit/retry
    传 scope（test_11）；UAT V4 工作流内 command(V4 识别) 成功；
    usage/evidence 新写入行自带 scope（store 层）。
24. parallel/loop/retry/timer/restart scope 证据：node/timer/branch
    插入即带 scope（_scope_cols 从持久化 run 读取）；test_12；
    backfill 修复历史 161/15/20 行；recovery_residue=0。
25. 首页 fixture 修复前后：before 见 §6；after：
    UAT V4 `home_zero_fixture_during_uat`/`home_zero_fixture_after_archive`、
    浏览器断言 home fixture 计数=0（browser_evidence.json）。
26. 日历 fixture 修复前后：before 外勤 13 可见/问卷 active 2/日程 5；
    after test_01/02/03 + live calendar=3（均 operational）。
27. recent objects 修复前后：before workflow 40/46、BI 10/20、
    project 14/14 混入；after test_04/05 绿、live recent 无 fixture。
28. activity 修复前后：before 全事件可见；after test_06（fixture run
    事件过滤）。
29. Supervisor 查询修复前后：before projects 未过滤；after test_07、
    负例 11 agent_projects=0。
30. BI/Finance 修复前后：before usage 全量聚合；after test_08/09、
    usage/evidence 不可变账本经来源 run scope JOIN 过滤。
31. 测试与证据中心功能：/api/v1/test-data/center + Web 区块
    （SystemStatus）：Test Run 历史/对象计数/一致性扫描/backfill
    账本；无删除按钮（仅查看/筛选/归档/扫描/导出）。
32. UAT V4 namespace：uatv4_20260812214006_d1wfbc（全新唯一）。
33. UAT V4 创建对象数量：center 计数 runs=4、work_items=5、
    customers=1、projects=1、field_tasks=1、surveys=1、
    assignments=1、responses=1、workflows=1、agent_runs≥2。
34. UAT V4 全链 ID：report.json（.eval/uat_scope_v2/uatv4/report.json）。
35. UAT V4 test_run_id 完整率：100%（`post_archive_test_run_full`）。
36. UAT V4 父子 scope 一致率：100%（`post_archive_parent_child_ok`）。
37. 归档后全 Domain operational 泄漏数量：0
    （`post_archive_leakage_zero`；gate
    `full_domain_fixture_leakage_zero` evidence="0 tables=[]"）。
38. Browser semantic assertions 数量：4 语义断言 + 6 响应式 = 10 pages。
39. 4 个 viewport 截图路径：.eval/uat_scope_v2/browser/si2_*_{1440,
    1280,1024,768}.png（sha256 记录于 browser_evidence.json）。
40. 浏览器 console/network 状态：console_errors_unexplained=0
    （已声明降级项：models/runtime 404、地图瓦片无 Key、ML-backend
    CORS）。
41. Gate evaluator 版本：2.1.0。
42. Gate checks 数量：26（见 .eval/uat_scope_v2/gate.json）。
43. Gate 负例结果：12/12 全部阻断
    （.eval/uat_scope_v2/gate_negative_tests.json）。
44. Gate source HEAD/代码树 hash/证据 hash：gate.json
    evidence_hashes（uat_report/browser_report/test_report/
    issue_ledger/code_tree/migrations/head）。
45. hermetic 测试结果：1399 passed, 1 skipped, 0 failed
    （.eval/uat_scope_v2/test_report.json）。
46. host_mps 测试结果：6 passed（pytest -m host_mps）。
47. TypeScript/Vite 结果：tsc --noEmit 0 错；vite build 成功
    （仅披露性 chunk 体积提示，未隐藏）。
48. 前端拆包前后体积：JS 2,712,322 B 单包 → index 63.77KB +
    vendor-react 164.52KB + 19 个 lazy chunk；gzip 818KB → 初始 ~72KB；
    BIWorkbench(gzip 382KB=echarts 全量)/Geo(255KB=maplibre) 无法再拆，
    已异步加载并在此披露（指令允许）。
49. 四服务状态：recognize/monitor/label_studio/app 全 UP
    （gate `services_healthy`）。
50. 当前模型与 hash：prod_v4_best_r1；detector.pt sha256=
    84bf9936189377007898c942a3c9a87f605d52c2afe01b7db2a66269e5554975
    （gate `current_bundle_v4`）。
51. 无训练进程声明：训练进程=0（gate `no_training_process`；
    abos status"训练进程：无"）。
52. production 未切换声明：CURRENT.json 未改动，仍 prod_v4_best_r1。
53. 未 merge/push/deploy 声明：本轮仅本地小步提交，无 merge/push/
    deploy（git log 可证）。
54. 未触碰用户资产声明：未导入正式数据、未删历史/训练/SAM/模型资产；
    归档全部追加式（visibility/superseded_at，行保留可审计）。
55. 未关闭问题：ISSUES.md 全部 CLOSED（SI2-001..010）。遗留观察项：
    app.log 历史存在 6 次 `run cancelled→succeeded 非法跃迁`异常
    （UAT V3 时代并发竞态痕迹，本轮未复现；建议后续轮次立 ISSUE
    跟踪，不影响本轮 scope 隔离结论）。
56. 最终 Gate：见 .eval/uat_scope_v2/gate.json（26 检查；状态以该
    机器文件为准——READY_FOR_REAL_DATA_UAT 仅在全部 26 项通过时输出）。
57. 用户下一步唯一需要做的事情：在浏览器打开
    http://127.0.0.1:8400 → 系统状态页查看"机器 Gate"与"测试与证据
    中心"，确认 Gate=READY_FOR_REAL_DATA_UAT 后，开始导入真实客户/
    地址/问卷进行真实数据 UAT（fixture 历史随时可在测试中心审计）。

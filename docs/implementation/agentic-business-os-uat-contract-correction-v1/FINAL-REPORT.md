# FINAL REPORT · UAT Contract Correction v1（45 项）

最终 Gate：`READY_FOR_REAL_DATA_UAT`（gate_evaluator 全条件通过；
不得写 ACCEPTED/COMPLETE/PRODUCTION_READY）。

1. **HEAD/branch/worktree**：HEAD `0f447e81`（提交本文档前为
   `0f447e81c604902c47101d4efe1342eadb08d9c1`）；branch
   `feat/nextgen-training-cycle-v2`；单 worktree，tracked 干净。
2. **commit 链**：f44c0f76(T0 审计+10 红测试) → bd56676e(T1 照片契约)
   → e0a478d3(T2 Agent 链) → 1de259aa(T3 并行) → ecd03ffa(判定器+校验器)
   → 98653f31(T6 限流) → 50398320(T5 shadow 纠偏) → 33bd4bcb(T4 UAT V2)
   → 4e9bcc2f(T7 浏览器修复) → 22142f5f/0f447e81(T8 CSS 契约/红测试终态)。
3. **完整阅读清单**：GLOBAL_AGENT_ROUTING、根 AGENTS.md、
   CODEX-PROJECT-HANDBOOK、USER-HANDBOOK、OPERATOR-RUNBOOK、
   MODULE-AGENT-DEV-GUIDE、V3 目录全部（04/05/ISSUES/STATUS/
   EXECUTION-LOG 重点）、survey/workflow/runtime/usage_api/两版预演
   脚本/shadow 脚本、近 30 commits、DB schema/迁移/服务/CURRENT/制品 hash。
4. **初始现场**：HEAD e45af4eb 与指令预期一致；四服务 UP；
   prod_v4_best_r1；detector sha `84bf9936…`；integrity ok；118 表；
   迁移 046；agent_call 12/12 无链；shadow sku 全 '?'；无训练进程。
5. **before 红测试**：tests/platform/test_uatcc_red_contracts.py
   10 failed + 1 守卫绿（RED-1..10 证据见 00-LIVE-AUDIT.md）。
6. **发现的问题**：UATCC-001..011（ISSUES.md：4×P0 + 7×P1，全 CLOSED）。
7. **每项根因**：见 01-ROOT-CAUSE-AND-CONTRACTS.md（RC-1..6）+
   UATCC-008/009/010/011 执行期新发现（_restore_ctx 丢输入/变量、
   loop body 可达性、retry body 解析、versions guard 参数冲突）。
8. **照片契约修复**：capture_role 五角色、min/max、require_storefront
   不得被 min_count=0 绕过、lint 冲突拒绝、submit 只校验可见题且错误
   指明题目与缺失类型、attach_media fail-fast、软删除 status 不计票；
   迁移 047；src/platform/survey.py + survey_api.py。
9. **门头必拍浏览器证据**：UAT V2 负证据（无门头照提交 409，错误文本
   "qsf(缺门头照 storefront…)"）→ 上传 storefront 照后提交成功
   （score=8.0）；QA 轮 svyfield 截图确认角色下拉与门头提示
   （.eval/v3_uat_v2/qa1_svyfield_*.png、qa3_svyfield_768.png）。
10. **media 绑定证据**：media_id 行含 response_id+question_id+
    capture_role（UAT V2 check "门头照绑定 response+question" 通过；
    ids.media_storefront/media_shelf 在 report.json）。
11. **Agent 统一身份模型**：每次 invoke 创建 BusinessRun
    （agent.invoke、parent/correlation/tenant/customer/project，
    缺失显式 unattributed）+ WorkItem + EvidenceBundle（cas_hash=
    trace sha256）；失败也写失败 run/证据/已耗 Usage；账本写失败
    fail-closed（不再 except: pass）；工作流 Agent 节点继承 parent run。
12. **Agent 新 Usage 完整率**：100%（UAT V2 窗口 4/4 run_id+work_id
    非空，source_evidence=evidence_bundle:*）。
13. **历史 Usage 处理**：12 条（其后现场又发现 4 条旧代码产生，共 16
    条 legacy）未篡改；`/api/v1/usage/reconcile-legacy` 追加式入账
    legacy_unattributed；Usage UI 徽章"历史未归属（无 run/evidence）"
    （qa1_finance_*.png）。
14. **Workflow 旧串行证据**：T0 审计确认 parallel 仅 frontier 扇出；
    RED-5 before：run failed/wall 无并行语义（00-LIVE-AUDIT.md）。
15. **新 parallel 实现**：workflow_branch_v1 durable 分支行、
    ThreadPoolExecutor(max_concurrency)、分支独立 ctx 深拷贝、
    join all/any/quorum、quorum 达成取消剩余、branch_timeout、
    变量合并冲突记录、recover_interrupted_parallels 分支粒度重跑。
16. **parallel wall-time**：两分支各 wait 2s：run 总链 2.98s
    （<3.5s 判定；串行基线≈4s+timer 轮询远超此值）；引擎测试通过。
17. **join all/any/quorum**：test_uatcc_parallel_engine.py 覆盖
    all 失败→run failed；any 一败一成→成功；quorum 2/3→成功+剩余取消；
    timeout 分支→run failed（wall<3s 证明超时生效）。
18. **重启恢复**：UAT V2 第 10 段：20s 持久 timer run 在
    `./bin/abos restart` 后由轮询恢复并 succeeded
    （run-009221805128）；并行分支恢复有单元覆盖；重启后 CURRENT 仍
    prod_v4_best_r1。
19. **UAT V2 namespace**：`uatv2_20260812170359_5vqash`（最终轮；
    此前迭代轮 ns 均独立不复用）。
20. **客户**：uatv2_…_cust（+ 跨客户隔离用 _cust2），master API 新建，
    inserted=1/skipped=0。
21. **项目**：uatv2_…_prj（budget.total=10000）。
22. **SKU**：uatv2_…_sku（canonical_name UAT2 测试可乐）。
23. **员工**：geo/employees 新建（employee_id 由服务端生成，记录于
    report.json ids.employee）；地址经导入中心 inserted=1。
24. **角色权限**：六角色（owner=bill / project_manager / field_manager+
    survey_designer / analyst / finance_operator / read_only 作 auditor）
    全部真实登录；矩阵 9 条含跨客户 403、auditor 写被拒 403、
    iam.check master.manage=false。
25. **地址**：stores_addresses_v1 导入 inserted=1；地理编码诚实降级
    （无 Key）+ manual-coords；地图数据/围栏页正常。
26. **路线**：nearest_neighbor_heuristic 规划 + adjust 生成 v2 版本。
27. **问卷全部题型**：客户/项目/SKU（sku_ref）/单选/多选/填空/打分/
    matrix/description + 跳题（关门跳过拍照）+ 自动评分（weight）+
    门头必拍 + 商品照片识别（v4_best_standard）+ 人工确认（accepted）。
28. **真实照片**：bad_samples/36143897_reflection.jpg 作为门头照与
    货架照上传（capture_role=storefront/shelf，含位置/时间/设备元数据）。
29. **完整工作流**：项目启动→外勤任务→等待到店(wait timer)→问卷条件
    (condition $vars.survey_done)→parallel（质量门 transform ∥ wait
    1s）→join all→人工批准(waiting_human→approved)→Analytics Agent→
    loop→end；另有失败重试（同 run retry 成功）、暂停→恢复→取消
    （paused→running→cancelled）、取消终态。
30. **Agent 调用**：Supervisor 直接提问/Survey Agent/工作流 Agent 节点/
    Analytics Agent（带客户+项目）/失败案例（无定义 Agent 409 且仍写
    失败 run）五场景全过。
31. **V4 识别**：/api/v1/commands vision.recognition.create
    （v4_best_standard）succeeded；run=run-2a15a4148b4d46b1 等；
    Usage 双单位（recognition_photo + model_compute_ms）。
32. **人工确认**：survey media review accepted → suggestion_status=
    accepted（final 与 suggestion 分离显示于 UI）。
33. **BI 指标**：受限公式 recognition.photos/recognition.photos 创建成功；
    evaluate/drilldown 客户隔离；data-products 血缘 8 产品。
34. **Dashboard**：dash-540e92f9dc（bar/line/number widgets +
    customer 过滤器，持久化 bi_dashboard_v1）。
35. **异常追问**：anomalies/check 返回 observed/threshold/hit
    （本窗口 hit=false 诚实输出）；报表 rep-d2a28095cd5b approve→
    publish→versions count=1。
36. **Usage 下钻**：finance 角色 rows 中识别行 run_id=
    run-2a15a4148b4d46b1、evidence_bundle_id 非空（usage-6d248822f6ba…）。
37. **首页闭环**：home/dashboard 八段齐全；Supervisor 六问全答
    （rules_tool_loop/rules_fallback 诚实标注）；reconcile consistent=true。
38. **V4 shadow 纠偏**：.eval/shadow_v4_best_report_v2.json——sku_name
    真实解析（佳得乐蓝莓/乌龙茶等）、sku_id/status/conf/margin/box、
    detector/classifier/registry/threshold sha256、负样本 0 accepted、
    load smoke/detection comparison/latency 口径分离、诚实声明四条；
    旧报告保留未动。
39. **当前模型和 hash**：CURRENT=prod_v4_best_r1（previous=
    prod_20260805_v5_r1 回滚在位）；detector.pt `84bf9936…`、
    classifier.pt `8a7a7f4c…`（与 v5 bundle 同 classifier SHA）；
    model_status=USER_SELECTED_UAT_MODEL（API+训练页横幅）。
40. **rate limit**：9 能力固定窗口+burst+Retry-After，SQLite 持久化；
    登录 429 实证（RED-9 绿）；拒绝审计事件；管理员规则修改+审计；
    系统状态页规则/命中表（qa1_status_*.png 命中 45）；9 专项测试通过。
41. **测试结果**：hermetic `1359 passed, 1 skipped, 6 deselected`；
    host_mps `6 passed`；tsc --noEmit 无错误；vite build 成功。
42. **SQLite/API/服务/浏览器**：integrity ok；迁移 048；139 API 步
    全部留痕（report.json api_steps）；stop→全 DOWN / start→四服务 UP /
    doctor 全绿、训练进程无；浏览器 3 轮 QA 55 截图，console 0（除已
    记录诚实降级：瓦片无 Key、ML-backend health CORS、models/runtime
    404 轮询）。
43. **production/训练/部署声明**：production=false（未部署任何线上）；
    training_started=false（本轮零训练）；deleted_files=false；
    未 merge/push/force-push；V4 为 USER_SELECTED_UAT_MODEL 而非
    PRODUCTION_APPROVED。
44. **未关闭问题**：无 P0/P1 遗留。诚实披露（非 Gate 阻断）：
    ① 嵌入式浏览器视口物理固定（1440/1280/1024/768 为命名约定，
    实际 856–1124 CSS 宽渲染，响应式在该区间验证）；② 地理编码/瓦片
    无 Key（degraded + 配置指引）；③ 同步执行引擎下 pause 仅在
    run=running 窗口可操作（已文档化）；④ 第 2 轮 QA 截图子系统超时，
    以 DOM/console 复核 + 第 3 轮补采替代（已如实记录）。
45. **最终 Gate 和用户唯一下一步**：Gate=`READY_FOR_REAL_DATA_UAT`。
    用户唯一下一步：用真实客户/地址/问卷/照片执行 05-UAT 手册的真实
    数据 UAT（可选配置 GEOCODER_PROVIDER/AMAP_API_KEY/TENCENT_MAP_KEY/
    MAP_TILES_URL 以启用地理编码与瓦片）；如需晋级模型准确率，先建立
    独立人工真值集再走 shadow→评估→审批切换链。

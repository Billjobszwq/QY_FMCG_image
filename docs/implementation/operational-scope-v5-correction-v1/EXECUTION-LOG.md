# EXECUTION-LOG — operational-scope-v5-correction-v1

时间均为本地时间（UTC+8），按顺序追加。

## 2026-08-13 开工基线

- 16:20 确认基线：branch=feat/nextgen-training-cycle-v2 HEAD=8e31708d584459fb38fedefe21b070bede36db57，tracked 工作树干净（32 个未跟踪目录均为数据/模型产物，不触碰）。
- 16:21 abos status：app/recognize/monitor/label_studio 全 UP；production=prod_v4_best_r1；训练进程 0。
- 16:23 sqlite backup API 备份 → .platform/backups/platform_pre_osv51_correction_20260813T162315.sqlite；备份与原库 integrity_check 均 ok。
- 16:26 BEFORE-STATE.md 落盘（HEAD/worktree/服务/进程/CURRENT/迁移/Gate/批次数量/导入作用域）。
- 16:27 快照五份证据到 before-snapshots/（gate.json、uatv7_report.json、test_report.json、browser_evidence.json、gate_negative_tests.json）。
- 16:28 启动全量 hermetic pytest 后台基线运行（记录真实失败，不采用静态 test_report.json 的 0 failed 口径）。
- 并行理解阶段：10 路阅读器（handbook/runbooks/scope 治理/gate 证据/import 管线/并行引擎/IAM users_v1/前端/registry 报告/DB 血缘）。
  - 并行引擎（已完成）：确认 run finalize 无条件 UPDATE 覆盖 timeout→cancelled 为根因，共 6 处竞态点。
  - scope 治理（已完成）：V5 自记 2 项未关闭 P1（UAT 批次残留、import 历史缺客户作用域），与本轮任务吻合。
  - registry/报告（已完成）：确认 gate_negative_tests.json 为手工静态文件、osv5_gate_evaluate.py 会覆写 UAT report.json（13 份过期报告漂移源头）、"42 checks"为 V5 生成时真值后被代码新增 10 条 check 漂移、Registry 125→126 漂移源头在 scope_registry.json 追加 md_customer_v1 后报告未同步。

## 2026-08-13 实施记录（W1-W6）

- W1-a（C-5）：parallel 终态竞态修复——_branch_row 全部终态写改条件
  UPDATE + rowcount；迟到 worker 回写被拒；test_branch_timeout 改有界
  drain 确定性断言；新 100 轮压力测试 test_osv51_parallel_stress.py
  （all/any/quorum/外部取消/branch/run timeout/重启恢复，零漂移）。
  提交 d09f15bf / 4770eba3 / c6af1d10。独立复跑 3 次全绿 +
  OSV51_STRESS_ROUNDS=150 种子 77 通过。
- W1-b（RC-9）：kb_search 全量态 flake 根因 = tests/contract 导入
  src.common.config 将 .env 生产 DEEPSEEK_API_KEY 灌入进程 →
  AgentRuntime 走真实远端 LLM 非确定性答复。client fixture 隔离
  provider 环境 + urllib 零外呼断言。提交 7a19c53d / 185511b1。
- W1-c（C-7）：ScrollManager（history.scrollRestoration=manual；
  PUSH/REPLACE → scrollTo(0,0)+focus h1+aria-live；POP 恢复历史
  位置）。提交 5bc228f3 / 6d5f1140。四视口真实浏览器验收待最终 QA。
- W2-a（C-1）：quarantine 写逃逸闭环（红 32/49 failed → 绿 52）；
  UI 写冻结横幅；Gate 负例 13/14/16 + quarantine_execution_escape /
  quarantine_no_operational_writes（BLOCKED_BY_IMPORT_SECURITY）；
  QA_REPLAY_DETECTED 证据入账 live DB（evidence+audit 各 1，幂等）。
  提交 b12d92ff / fb18e231 / 3c786897 / 3ec5cbd9。
- W2-b（C-2）：首次密码零持久化（红 7 failed → 绿 10）；熵 32→128bit；
  落库脱敏 + DTO 递归扫描 + scrub 脚本（live DB 0 命中）；Gate 负例
  15 recursive_secret_scan。提交 e9ca7c91 / 30f0c17f。
- W3（C-3）：隔离区裁决状态机——迁移 060 + CAS + 双人审批 +
  revision 创建 + UI 裁决面板（红 15 failed → 绿 15）。live DB 迁移
  应用；三个隔离批次经 API 裁决为 retained_for_evidence（继续隔离
  留证；最终处置保留给用户）。提交 cc5600f4。
- W4（C-4）：17 批血缘确定性回填（12→29 关联行；0 pending；3
  quarantine 待裁决；逐批审计含 batch_id；幂等）；Gate
  import_batch_association_complete；UI 未绑定/待裁决显示（禁“全局”
  误导）。提交 78964124。
- W5（C-6）：证据 binding 块 + 去自比较 + 实时复核（HEAD+tree+migration+
  worktree+db fingerprint）+ test_report 机器生成器 + 浏览器四视图截图
  去同字节缺陷 + 负例 17-21（12 项 binding 测试全绿）。提交 0d759fe6。
- W6（C-8）：osv51_machine_facts.py 机器事实源 + V5 历史报告更正附录。
  提交 5c166d66（代码冻结点）。
- 评估器版本 3.2.0 → 3.3.0（单点定义 + r30 版本钉同步）。
- 负例账本 12 → 21，全部 ALL_BLOCKED。

## 2026-08-13 验收链（代码冻结 HEAD=5c166d66 后执行）

- bin/abos restart：四服务健康；production=prod_v4_best_r1；训练 0。
- host_mps 独立：6 passed（1582 deselected）。
- 全量 hermetic：osv51_test_report.py 生成绑定报告（结果见
  machine_facts.json）。
- 全量 hermetic（第二次）：1 failed = tests/contract
  test_css_variables_all_defined（本轮 W3 裁决面板引入未定义 token
  var(--line)）→ 改 var(--border) 红→绿（222339f3）。
- 全量 hermetic（第三次/收尾）：**0 failed / 1581 passed / 1 skipped /
  6 deselected**（osv51_test_report.py 机器生成 + binding）。
- 期间诚实事故记录：test_report 解析器对全绿摘要误判 failed=-1
  （pytest 全绿不输出 “0 failed”）→ 修复解析器（全绿=0；无摘要=-1
  阻断），6aaa3a1f。不得以误报掩盖，也不得以误报阻断。
- host_mps：6 passed；100 轮压力：套件内 + 独立种子 777 通过（W1-a
  另跑 150 轮种子 77）。
- live 复核：integrity ok；Registry 126 条 problems=[]；三个隔离批次
  live API commit/dry-run 均 409 IMPORT_BATCH_WRITE_BLOCKED；live DB
  递归 secret 扫描 0 命中。

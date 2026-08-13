# ACCEPTANCE — V5.2 验收清单

执行顺序（最终 HEAD 上，任何代码/文档变更之后必须整链重跑）：

1. [x] 全量 hermetic（osv51_test_report.py，含
   -W error::pytest.PytestReturnNotNoneWarning）→ 0 failed / 0 该类
   warning（结果见 .eval/scope_v5/test_report.json + machine_facts）。
2. [x] host MPS 独立（-m host_mps）。
3. [x] TypeScript typecheck（tsc --noEmit）。
4. [x] Vite production build。
5. [x] 并发压力：business_run CAS 1500 轮恰一赢家 0 覆盖（套件内
   test_osv52_run_status_cas 300 轮 + 60 轮同目标；另独立 1500 轮
   实证脚本）；parallel 100 轮压力（V5.1 已固化）。
6. [x] 27 项 Gate 负例（原 21 + 篡改族 6）ALL_BLOCKED。
7. [x] 四视口浏览器 QA（含 URL 三方一致 4 视图×4 视口、未知 view
   规范化、首页 H1/焦点、滚动连续性、四视图截图互异）。
8. [x] SQLite integrity_check。
9. [x] Registry validator（validate_registry problems=[]）。
10. [x] stop/start/restart/doctor。
11. [x] 证据再生：UAT V7 / test / browser / negative 全部带 binding。
12. [x] 新 Gate 生成（evidence_manifest + gate_run_v1 candidate）→
    人工批准激活（POST /api/v1/control/gate/activate，approved=true）
    → 实时端点复核。
13. [x] 篡改演练：Gate 激活后重写 negative report → 实时端点立即
    BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT。
14. [x] 恢复路径：重跑 negative + gate 生成 + 重新激活（不手工改
    hash）。

## 放行条件核对（第九节）

- active Gate 使用显式 Registry（gate_run_v1），非 mtime：是
- 所有 evidence 当前 SHA 与 manifest 一致：由
  evidence_file_hashes_fresh 检查保证（freshness 复评每次重算）
- evidence 内容变化 → 实时 Gate 立即 STALE/HASH_DRIFT：篡改演练证明
- Import Center URL/view/API 三方一致：浏览器断言 16+1 项
- 全量 0 failed、0 warning（-W error 门禁）：见 machine_facts
- 首页 H1 + 焦点：home_unique_h1_focus 断言
- OSV51-013 结构性关闭：CAS + 实证
- P0=0、P1=0：ISSUES.md（OSV52-007 为 P2 登记项）
- production=prod_v4_best_r1、训练进程 0：bin/abos status

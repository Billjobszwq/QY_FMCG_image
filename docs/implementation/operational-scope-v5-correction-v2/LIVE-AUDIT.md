# LIVE-AUDIT — Operational Scope V5.2（as-of 2026-08-13 开工时点）

基线：feat/nextgen-training-cycle-v2 @ 8cb51dcf；四服务 UP；production
prod_v4_best_r1；训练 0；integrity ok；迁移 060；DB 备份
platform_pre_osv52_20260813T231549.sqlite（integrity ok）。

## 独立 QA（.gstack/qa-reports/qa-report-localhost-2026-08-13.md）复核

### ISSUE-001（High）证据文件哈希断链 — 已复现
- gate.json 记录 negative_report=3dd868a16e585276；QA 重跑负例脚本后
  当前文件 SHA=52da2afd4f9579f4；**实时 /api/v1/control/gate 仍返回
  READY_FOR_REAL_DATA_UAT**。
- 根因：freshness 复评只核对 HEAD/代码树/迁移/worktree/DB fingerprint，
  evidence_hashes 记录后从未被任何实时路径重算比对（V5.1 已知残留，
  understand/gate-evidence.md Risks 第 2 条）。
- 其余三份证据当前哈希一致（uat/test/browser）；断链只发生在 QA 重跑
  负例之后——但这正证明 Gate 后任何证据重跑/替换/损坏都不可见。

### ISSUE-002（Medium）Import Center URL 视图不随刷新恢复 — 待复现修复
`#/data/import?view=quarantine` 直连/刷新：URL 是 quarantine，页签选中
“运营导入”。根因：view 是纯组件 state，从不读/写 URL。

### ISSUE-003（Low）测试返回非 None — 已确认
test_first_commit_delivers_once 返回 tuple → PytestReturnNotNoneWarning；
`-W error::pytest.PytestReturnNotNoneWarning` 下失败。

### ISSUE-004（Low）首页无 H1 — 已确认
13 个一级路由仅 /home 无 H1；导航进入首页焦点停留在导航链接。

### 其他风险（QA）
- 实时 Gate 按 .eval/*/gate.json mtime 选择 → 旧 scope 重跑可接管
  系统状态 → 需显式 Active Gate Registry。
- vendor-maplibre 约 949KB（gzip 248KB）→ **登记 P2，本轮不重构**。
- OSV51-013（set_business_run_status SELECT-then-UPDATE）仍开放 →
  本轮结构性关闭。

## V5.2 判定

开工时刻实时 Gate 的 READY 不可信（证据哈希断链）。本轮第一步：实时
路径必须对断链返回 BLOCKED_BY_GATE_EVIDENCE_HASH_DRIFT；完成证据链
再生 + Active Gate 显式激活后才允许恢复 READY。

# 03-GATE-CONTRACT · 可信 Gate 2.1

## 状态机

```
BLOCKED_BY_UAT_FIXTURE_PROJECTION   全 Domain fixture 泄漏 > 0
BLOCKED_BY_SCOPE_LINEAGE            scope binding/test_run_id/父子一致率 < 100%
BLOCKED_BY_BROWSER_SEMANTICS        浏览器语义断言失败
BLOCKED_BY_STATE_PROJECTION         终态漂移/投影不一致
BLOCKED_BY_GATE_EVIDENCE            证据缺失（报告/测试/服务/截图）
STALE_GATE_EVIDENCE                 Gate 生成后代码/证据变化
READY_FOR_REAL_DATA_UAT             全部检查通过
```

## 绑定（P1-004 修复）

Gate 必须记录并复评校验：

- source_commit == 当前 HEAD（git rev-parse）；
- tracked worktree 干净（git status --porcelain 无 tracked 变更）；
- 关键代码树 hash（src/platform、web/src、scripts 的
  git 对象级 hash 或文件 sha256 聚合）；
- migration hash（schema_migrations 全量 sha 聚合）；
- report/browser/test/ISSUES hash（已有机制保留）。

任一不匹配 → `STALE_GATE_EVIDENCE`，不得展示旧 READY。

## 检查清单（T6 实现，≥25 项）

全 Domain operational 查询泄漏=0（customer/project/sku/survey/
assignment/response/media/field/route/geofence/calendar/workflow/
run/node/timer/branch/approval/agent/message/recognition/evidence/
usage/BI/anomaly/followup/Home/Supervisor/recent/activity/search），
scope binding 完整率=100%，test_run_id 完整率=100%，父子一致率=100%，
名称模式不误判 operational，HEAD 绑定，worktree 干净，代码树 hash，
migration hash，浏览器语义断言，测试/MPS/typecheck/build，服务健康，
SQLite integrity，CURRENT=prod_v4_best_r1，训练进程=0。

## 证据数字规范（P2-001 修复）

所有计数 evidence 必须为显式数字字符串（"0" 也显示 0），
禁止 Python falsy/or 产生 None。

## 浏览器语义证据（T7）

browser_evidence.json 每项：route/viewport/expected_object_type/
expected_object_id/actual_object_id/expected_text/actual_text/
selector/assertion/screenshot/sha256/console_errors/network_errors。
Gate 校验 actual_object_id == expected_object_id。

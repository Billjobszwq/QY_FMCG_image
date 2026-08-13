# 04-EVIDENCE-FRESHNESS — Gate 证据新鲜度闭环（C-6）

## 1. 绑定块规范（evidence binding block）

每份证据文件（uatv7/report.json、test_report.json、browser/browser_evidence.json、gate_negative_tests.json）顶层必须含：

```json
"binding": {
  "source_commit": "<git rev-parse HEAD @生成时刻>",
  "code_tree_hash": "<sha256[:16] over src/platform+web/src+scripts，同评估器算法>",
  "migration_hash": "<sha256[:16] over schema_migrations 名单>",
  "database_fingerprint": {"scope_graph": "...", "event_watermark": N, "outbox_pending": N, "counts": {...}},
  "suite_config_hash": "<sha256[:16] over pyproject [tool.pytest.ini_options] + marker 口径>",
  "command_hash": "<sha256[:16] over 生成命令行>",
  "result_hash": "<sha256[:16] over 结果主体（不含 binding 自身）>",
  "started_at": "...", "finished_at": "..."
}
```

**禁止**：gate 生成时把当前值同时填入 recorded/current 形成自比较。recorded 永远来自证据文件 binding 块；current 由评估器现场独立计算。证据缺 binding → BLOCKED_BY_GATE_EVIDENCE（missing_binding）。

## 2. 各生成器改造

| 生成器 | 改造点 |
|---|---|
| scripts/uatv7_rehearsal.py | 运行开始/结束采集 binding；**删除/禁止 gate 评估路径覆写 report.json**（osv5_gate_evaluate.py 只读消费） |
| scripts/osv51_test_report.py（新） | 包装 hermetic pytest（subprocess 或解析 junit/终端摘要），写 test_report.json + binding；手写 JSON 废止 |
| scripts/osv5_browser_evidence.py | 采集时写 binding（含 web/dist 构建产物 hash 或 code_tree_hash 的 web/src 口径）；修复 4 张 Import 视图截图字节相同的采集缺陷（OSV51-010：切换视图后等待渲染/强制 reflow 再截图） |
| scripts/osv5_gate_negative.py | 输出 binding；新增负例见 §4 |
| scripts/osv5_gate_evaluate.py | 去自比较：recorded_* 从各证据 binding 读取；逐项比对 current；任一不符 → 对应 check false |

## 3. Gate 新增/改造检查

- `uat_evidence_binding_fresh`、`test_evidence_binding_fresh`、`browser_evidence_binding_fresh`、`negative_evidence_binding_fresh`：binding 存在且 source_commit/code_tree_hash/migration_hash/database_fingerprint 与当前一致；不符 → block=STALE_GATE_EVIDENCE。
- 实时路径（control_plane_api → re-evaluate）：在 HEAD + db_fingerprint 之外增加 code_tree_hash、migration_hash、tracked_worktree_clean 复核（5s 缓存沿用）。
- 语义保证：代码修改后不重跑测试 → test binding 不符 → STALE；DB 修改后不重跑 UAT → uat db_fingerprint 不符 → STALE；前端修改后不重跑浏览器 QA → browser binding 不符 → STALE。

## 4. 负例（osv5_gate_negative.py 新增）

1. `stale_code_without_rerun_tests`：构造 test binding 的 code_tree_hash ≠ current → STALE；
2. `stale_db_without_rerun_uat`：构造 uat binding 的 database_fingerprint ≠ current → STALE；
3. `stale_frontend_without_rerun_browser`：browser binding code_tree_hash ≠ current → STALE；
4. `missing_binding_detected`：去掉某证据 binding → BLOCKED_BY_GATE_EVIDENCE；
5. `self_compare_injection`：模拟 recorded==current 但证据文件无 binding（旧行为）→ 不得 READY。
保留既有 12 项 + quarantine_execution_escape + recursive_secret_scan + association completeness 相关。

## 5. 执行顺序契约（本轮收尾强制）

代码冻结（最后一次 commit）→ bin/abos restart → 全量 hermetic pytest（osv51_test_report.py 生成）→ host_mps 独立 → uatv7_rehearsal.py → osv5_browser_evidence.py（四视口）→ osv5_gate_negative.py → osv5_gate_evaluate.py 最后。任何后续代码/DB 变动必须整链重跑；gate 恢复 READY 仅允许在全部证据重生成之后。

## 6. 本轮即时语义

当前全量 1 failed（OSV51-008）+ 代码即将修改 → test_report 重生成必为 failed≥1 直至修复 → Gate 必须非 READY。修复完成并全链重跑前不得恢复 READY（任务书第七条第 7 款）。

## 7. D-11 精化：证据级 DB 比对的 scope_graph 豁免

证据 binding 的 database_fingerprint 比对键为 event_watermark /
outbox_pending / projection_hash / counts；**scope_graph 豁免**（证据
运行自身 fixture 生命周期合法移动该聚合）。运营数据漂移防线：
1) Gate 全量评估直接重算 leakage/residue/lineage/quarantine 归因；
2) gate.json 顶层 db_fingerprint（证据链结束后生成）与实时端点全键
比对（含 scope_graph）→ 任何证据后 DB 变化仍触发 STALE。

# 05-BROWSER-UAT — 浏览器验收口径（OSV51）

## 1. 工具链

- `scripts/osv5_browser_evidence.py`：CDP 驱动本机 Chrome（debug 端口
  9227），真实角色（owner/platform_admin、read_only、auditor 浏览器
  角色 + customer_admin/project_manager API 矩阵），对象级断言
  （DOM 行数/ID == API 口径），四视口 1440/1280/1024/768。
- 证据：`.eval/scope_v5/browser/browser_evidence.json` + PNG；OSV51 起
  携带 binding 块（source_commit/code_tree_hash/migration_hash/
  database_fingerprint/suite_config_hash/command_hash/result_hash/
  started_at/finished_at）。

## 2. OSV51 新增断言

1. **四视图截图互异**（OSV51-010 修复）：Import Center 四视图切换后
   强制滚动归零 + 重排同步 + 同字节重载重试；Gate 检查
   `browser_import_views_distinct`（sha 全同 → BLOCKED_BY_BROWSER_SEMANTICS）。
2. **导航滚动连续性**（C-7）：`nav_scroll_continuity` 四视口断言——
   Import Center 深滚（y≈2124）后经主导航进入系统管理：新页面
   `window.scrollY==0` 且 `document.activeElement` 为 h1（ScrollManager：
   PUSH/REPLACE 归零聚焦 + aria-live 播报；POP 恢复历史位置）。
3. **隔离区裁决面板**：quarantine 详情渲染写冻结横幅 + 裁决状态/
   动作区（data-testid=quarantine-adjudication / adjudication-state）；
   dry-run/提交按钮不再对隔离批次渲染。
4. **首次密码**：详情回执不再出现明文初始口令（[REDACTED]）；
   文案为“仅提交当次响应可见”。

## 3. 判定

- `browser_semantic_assertions`：全部 page 断言（含新增）通过。
- `browser_viewports_covered` = {1440,1280,1024,768}。
- `browser_console_clean`：未解释 console 错误 = 0。
- `browser_evidence_binding_fresh`：binding 与当前 HEAD/树/迁移/DB 一致，
  否则 STALE_GATE_EVIDENCE。

## 4. 本轮执行记录

见 EXECUTION-LOG“验收链”与 machine_facts.json → browser.*。

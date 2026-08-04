# Platform V2 — ISSUES

> 格式：ID | 状态 | 严重度 | 描述 | 处置

| ID | 状态 | 严重度 | 描述 | 处置 |
|---|---|---|---|---|
| PV2-001 | OPEN | 高 | 8300 Label Studio 未运行，标注审核不可用 | 8400 显示 degraded；M4 修复 start_label_studio.sh 路径后恢复 |
| PV2-002 | OPEN | 高 | 8301 ml-backend、8304 orchestrator 未运行 | 8400 显示 degraded；M4 处理 |
| PV2-003 | OPEN | 中 | `src/eval/truebox_eval.py` 的 recall@FP 实为 recall@TopK（每图取 top-K proposal，非真实 FP/photo 预算扫描） | 手册 §2.5.4 确认；M5 修复；当前不得用于任何晋级判断 |
| PV2-004 | OPEN | 中 | 旧 `/retrain` 的 auto_switch=true 不合规 | 新平台禁止该语义；M5 训练与发布分离审批 |
| PV2-005 | OPEN | 中 | `src/ls_platform/jobs.py` daemon thread 不可靠恢复（orphaned 无法识别） | M2 Job/Attempt 状态机 + M6 可靠 Worker 解决 |
| PV2-006 | OPEN | 低 | 8455 omlx 根路径 404（进程在，健康端点未知/需 API key） | W2 适配器按 unavailable/degraded 标记，探测路径待确认 |
| PV2-007 | CLOSED | 低 | 分支切换时工作树有未提交改动（README/program 索引切换 + 新手册文件） | 确认为用户为新手册做的入口切换，随 feat/usable-platform-foundation 保留并纳入 M0 提交 |

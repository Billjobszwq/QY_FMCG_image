# NextGen V2 · ISSUES

## N2-ISSUE-001 交付报告计数纠偏
- 状态：CLOSED（Task 0）。上一报告默认 1010 passed 在本机成立，但 Codex 受限环境
  fresh 为 1002/8 failed；根因为测试宿主 MPS 耦合。已 hermetic 化并留 host suite。

## N2-ISSUE-002 未跟踪证据分类
- 状态：OPEN（Task 0）。reports/backfill_visible_sku/*.json（3 个）与
  reports/gltc_web_qa_training_console.png 为历史证据，保留不删除，随 docs commit 分类归档。

## N2-ISSUE-003 V1 控制链缺口（承接 01 审计 §6）
- NextGen API 写链不全、dataset build 固定空 rows、Graph 内存态、Web 只读卡、
  识别页无 profile。由 Task 1/2/7/10/11 关闭。

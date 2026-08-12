# EXECUTION LOG（追加式）

## 2026-08-12 · T0 现场复现

- HEAD 6cbca9c0 与预期一致；四服务 UP；无训练。
- DB 复现：4 cancelled run 主 work 活动态；3 succeeded run approval
  残留；agent.invoke failed=0；15 uat 客户；首页 todos 含 3 running+
  1 waiting+3 blocked+3 approval 漂移残留。
- 取证 run-df31c2f6b8a3：cancel 后 20s 分支仍 parallel_joined；
  work 在后续 reconcile 时段被推回 running。

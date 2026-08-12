# DECISIONS（追加式，不覆盖）

| ID | 决定 |
|---|---|
| C-001 | 旧 v1 预演报告保留为历史 smoke evidence，不覆盖；UAT V2 独立目录 `.eval/v3_uat_v2/` |
| C-002 | 历史 12 条无链 agent_call Usage 不篡改；追加式 attribution 账本，UI 标"历史未归属" |
| C-003 | parallel 若本机线程池可行则真实并行；任何情况下不得以串行冒充并在 Gate 写完成 |
| C-004 | V4 状态口径改 `USER_SELECTED_UAT_MODEL`（无独立人工 GT 不写准确率结论）；保持 prod_v4_best_r1 与回滚路径 |
| C-005 | rate limit 用 SQLite 持久化窗口计数；默认额度宽松不影响正常 UAT；管理员可调 |
| C-006 | 测试一律使用独立 tmp DB fixture，不碰运行中真实服务与真实 DB |

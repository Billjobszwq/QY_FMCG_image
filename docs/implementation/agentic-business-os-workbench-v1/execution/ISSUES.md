# Execution Issues

| ID | 节点 | 严重度 | 状态 | 问题 |
|---|---|---|---|---|
| EX-001 | T0 | info | closed | zsh 中 for 循环变量名 `path` 会覆盖 PATH（zsh path↔PATH 绑定），导致后续命令 command not found；已恢复并改用 `p` 变量名 |
| EX-002 | T11 | bug | closed | bin/abos 探测函数 curl 失败时输出双 000 造成假 UP；改 http_code 单值返回 |
| EX-003 | T11 | bug | closed | monitor_watchdog 守护会自动拉起 8092；stop 先停 watchdog |
| EX-004 | T13 | bug | closed | supervisor 识别任务查询 ORDER BY id（无此列）被宽泛异常吞为 0；改 rowid |
| EX-005 | T13 | ui | open | ≤1024px 面板遮挡已加收起/展开；精确四视口验收受工具限制 partial |
| EX-006 | T12 | info | open | rate limit 与 trace 全链自动对账脚本列入下一实施包 |

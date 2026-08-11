# Execution Issues

| ID | 节点 | 严重度 | 状态 | 问题 |
|---|---|---|---|---|
| EX-001 | T0 | info | closed | zsh 中 for 循环变量名 `path` 会覆盖 PATH（zsh path↔PATH 绑定），导致后续命令 command not found；已恢复并改用 `p` 变量名 |

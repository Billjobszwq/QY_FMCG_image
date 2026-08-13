# 03 · 可执行 Scope Registry（OSV5 T4）

原则：表名进 Registry ≠ 治理完成；只有创建/授权/运营查询/归档/
测试中心/BI/Gate/浏览器/证据链全部由同一可执行策略驱动才算接入。

- 声明类型化：pk（真实列 | composite: | none）、tenant_strategy
  （not_applicable=本地单租户）、customer/project 策略（column |
  derive | not_applicable）、scope_cols、parent edges、op/archive
  handler 键。
- validate_registry(conn)：表/列/PK/edge/handler 全部机器校验；
  启动测试与 Gate 消费；非零错误 → BLOCKED_BY_SCOPE_REGISTRY。
- 派生消费：leak_scan_tables()（scanner）、archivable_tables()+
  archive_handler_for()（archiver）、operational filter、Test
  Center count_tables、Gate coverage。平行硬编码清单收敛。
- 新 scoped 表未登记/缺 handler → Gate 自动阻断。

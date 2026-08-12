# DECISIONS · UAT Scope Isolation V2

| ID | 决策 | 理由 | 否决项 |
|---|---|---|---|
| DEC-SI2-001 | 唯一事实源 = 业务表统一 scope 字段（方案 A）；`object_scope_binding` 只做只读派生 VIEW | 已有 3 表带字段；避免平行真相与对账成本 | 方案 B 独立 registry（会漂移） |
| DEC-SI2-002 | scope 逻辑集中在 `src/platform/scope.py`，各模块注入使用 | 指令 4.2/五 T2 禁止复制多版本逻辑 | 各模块内联 SQL 过滤 |
| DEC-SI2-003 | 默认 operational：普通查询/API 一律 `COALESCE(data_scope,'operational')='operational'` | fail-closed：NULL 视作 operational 历史行，backfill 后再收紧 | 默认全量展示 |
| DEC-SI2-004 | 名称模式仅用于一次性 legacy backfill（迁移 051 内含 backfill + 审计账本表 `scope_backfill_audit_v1`） | 指令 P1-002 | 运行时 LIKE |
| DEC-SI2-005 | Gate 投影降级写入新文件 `.eval/uat_scope_v2/gate.json`，旧文件不删 | 指令 T0：保留历史证据 | 覆盖旧 gate.json |
| DEC-SI2-006 | UAT V4 先建 Test Run 上下文再建对象（API `POST /api/v1/test-data/run`） | 修复 test_run_id 不贯穿 | 先建后补标 |

# DECISIONS · Scope Integrity V3

| ID | 决策 | 理由 | 否决项 |
|---|---|---|---|
| DEC-SI3-001 | effective scope = 行自身列 ⊕ 父链推导；运营查询与 Gate 一律消费 effective 口径 | 假阳性根因是只看自身列；父链才是事实 | 继续补丁式加列 |
| DEC-SI3-002 | 唯一上下文载体 ExecutionContext（scope.py），全模块注入消费 | 指令四.1/2；消除多份拼装 SQL | 各模块自拼过滤 |
| DEC-SI3-003 | 不可变 Usage/Evidence 不改原行，经 scope_attribution_ledger_v1 追加式绑定计算 effective_scope | 红线三.3 不可篡改账本 | UPDATE 历史 usage |
| DEC-SI3-004 | Test Run registry fail-closed：test_run 必须存在且 current；重复创建内容一致才幂等，否则 409；禁止 INSERT OR REPLACE | 指令四.5/6/9 | REPLACE 覆盖 |
| DEC-SI3-005 | 全表 Scope Registry（src/platform/scope_registry.py）为机器事实源，Gate 检查覆盖率=100% | 指令五；防止未登记表绕过扫描 | 只登记域表 |
| DEC-SI3-006 | Gate 3.0 freshness：control/gate 实时复算绑定（DB fingerprint/水位/投影 hash），可缓存但 DB 变化必须 STALE | 指令九.3/4；静态 JSON 已被证伪 | 静态 gate.json |
| DEC-SI3-007 | scanner 全路径 fail-fast；异常即 BLOCKED，禁止 except/continue | 指令九.5 | 吞异常放行 |
| DEC-SI3-008 | 历史纠偏一律追加式：可变对象结构字段修正，不可变账本走 attribution；每次回填写审计（规则/父对象/数量/hash/actor/commit/时间） | 指令六 | 删行/改账本 |
| DEC-SI3-009 | 名称 LIKE 仅允许一次性 legacy backfill 且留审计；运行时禁用 | 指令六.7 | 运行时 LIKE |
| DEC-SI3-010 | Gate 降级投影写 .eval/scope_v3/gate.json（mtime 最新被 control/gate 选中），旧 gate.json 保留为假阳性证据 | 红线三.3 不删历史 | 覆盖旧文件 |

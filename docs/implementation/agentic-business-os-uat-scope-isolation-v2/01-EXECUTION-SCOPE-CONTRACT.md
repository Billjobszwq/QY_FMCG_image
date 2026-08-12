# 01-EXECUTION-SCOPE-CONTRACT · ExecutionScopeV1

## 1. 唯一事实源决策（DEC-SI2-001）

方案选择：**A（统一作用域字段）为唯一事实源**，不建平行 registry。

理由：
- `business_run_v1`/`work_item_v2`/`md_customer_v1` 已有
  `data_scope`/`test_run_id` 字段且线上运行；
- 平行 registry（方案 B）会与业务表形成两个真相，需要额外对账，
  违反指令 4.4"禁止两个互不一致的平行真相"；
- 统一 `object_scope_binding` 视图（只读 VIEW）作为**查询加速与
  审计投影**，从业务表派生，不是第二事实源。

## 2. ExecutionScopeV1 结构

```
tenant_id      默认 "local"
customer_id    归属客户（可为 "" 表示 unattributed）
project_id     归属项目
data_scope     operational | uat_fixture | demo_fixture | system | archived
test_run_id    fixture 必填（= UAT namespace）
correlation_id 贯穿链
parent_run_id  父 Run
actor_id       发起者
source         web | api | agent | workflow | system | uat_rehearsal
created_at
```

`data_scope` 取值域固定为上列五种；客户端不得通过普通 header
自证 operational —— scope 一律由服务端解析（ScopeResolver）。

## 3. 解析顺序（ScopeResolver）

1. 显式 Test Run 上下文（UAT 预演先建 test_run，后建对象）；
2. 父 Run（parent_run_id → 继承父 scope，含 test_run_id）；
3. 父 WorkItem；
4. Customer/Project 主数据（`md_customer_v1.data_scope`）；
5. 默认 operational（仅当以上全部无 fixture 证据）。

## 4. 继承与 Fail-closed（ScopePolicy）

所有下游对象创建时必须与父 scope 一致；下列情况拒绝执行：

- 父 fixture、子请求 operational → `SCOPE_CONFLICT_FIXTURE_TO_OPERATIONAL`
- 子与父 data_scope 不一致 → `SCOPE_CONFLICT_PARENT_CHILD`
- data_scope=uat_fixture 但 test_run_id 为空 → `SCOPE_MISSING_TEST_RUN_ID`
- customer/project 与 scope binding 冲突 → `SCOPE_BINDING_CONFLICT`
- Usage/Evidence 无来源 Run → `USAGE_LINEAGE_MISSING`

## 5. 落库契约

- scope 写入与业务对象 INSERT 处于同一连接/同一提交批；scope 字段
  写入失败则业务对象不得成功（同事务语义）；
- 恢复路径（timer/retry/restart）一律从 DB 行读 scope，不从进程内
  变量猜测；
- 运行时查询禁止 `LIKE 'uat%'` 等名称模式；名称模式只允许出现在
  一次性 legacy backfill 脚本，并输出审计账本。

## 6. 模块入口

`src/platform/scope.py`（唯一实现，禁止各模块复制逻辑）：
`ExecutionScopeV1` / `ScopeResolver` / `ScopePolicy` /
`ScopedQuery`。

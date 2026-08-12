# 01-SCOPE-GRAPH-CONTRACT · 统一 ExecutionContext / Scope Graph（V3）

> 取代 SI2 的"行自身列 + 补丁式绑定"模型。V3 的核心：所有模块只
> 消费**一份** ExecutionContext；对象的 effective scope 由**父链
> 推导**而非仅自身列；一切写入在同一事务内完成。

## 1. ExecutionContext（唯一上下文对象）

```
ExecutionContext {
  tenant_id        # 租户（当前固定 local）
  customer_id      # 归属客户（可空=平台级）
  project_id       # 归属项目（可空）
  data_scope       # operational | uat_fixture | demo_fixture | system
  test_run_id      # fixture 必填；必须在 uat_test_run_v1 且 status=current
  correlation_id   # 关联链
  parent_run_id    # 父 BusinessRun
  actor_id         # 发起者
  source           # api | workflow | agent | recovery | backfill
  definition/artifact/version  # 触发定义与版本（工作流/Agent/模型）
}
```

实现：`src/platform/scope.py::ExecutionContext`（V3 起为唯一载体；
`ExecutionScopeV1` 保留为别名过渡）。所有模块（Agent、Workflow、
Command Gateway、模型调用、人工批准、失败路径、recovery、backfill）
**只能消费这一份上下文**，禁止各自拼装 SQL 过滤。

## 2. 解析规则（ScopeResolver V3，fail-closed）

解析顺序：**Test Run registry → 父 Run → response/assignment 父链 →
Customer 主数据 → operational**。

1. `test_run_id` 非空 → 必须在 `uat_test_run_v1` 存在、
   `status='current'`，且请求者有权（与登记 actor/customer 集匹配）。
   archived / 不存在 / 他人上下文 → `ScopeViolation` fail-closed。
2. fixture 上下文中客户自证 `data_scope=operational` → 拒绝
   （客户端不得自证 operational）。
3. fixture 客户（data_scope fixture 或 is_test_fixture=1）下创建
   对象必须解析出 fixture scope；解析不出 test_run 时继承该客户已
   登记的最近 archived 上下文只允许只读，写入必须显式新上下文。
4. 父 Run 存在 → 全字段继承（data_scope/test_run/customer/project/
   tenant/correlation）；显式入参与父链冲突 → 拒绝。
5. 失败路径（Agent 定义缺失等）**先解析 scope，再查定义**；即使
   定义不存在，Run/Work/Evidence/Usage 也必须落正确 scope。

## 3. 父子一致性（ScopePolicy V3）

`check_child(parent, child)` 必须校验全部六维：
tenant / customer / project / data_scope / test_run / correlation。
- fixture 父对象不得产生 operational 子对象；
- 同 scope/test_run 但 customer/project 不一致 → 拒绝；
- 违规抛稳定错误码（`SCOPE_CONFLICT_*`），API 层映射 409。

## 4. 事务原子性

- 对象创建与 scope 写入**同一事务**；禁止"先 commit 再 bind"。
- Test Run namespace 不可覆盖：禁止 `INSERT OR REPLACE`；
  重复创建仅当内容完全一致时幂等返回，否则 409。
- 白名单绑定（bind_fixture_scope）保留给迁移/回填工具；运行时
  创建路径一律走"同事务写入"。

## 5. 继承矩阵（必须全部生效）

| 子对象 | 继承自 | 通道 |
|---|---|---|
| Work/Evidence/Usage/Node/Timer/Branch/Approval/DeadLetter | BusinessRun | run_id 父链 + 同事务列写入 |
| recognition_task | BusinessRun（command/媒体触发） | run_id + scope 列 |
| survey_media | survey_response（→assignment→customer/test_run） | response_id 父链 |
| 媒体触发的识别 | 所属 media/response scope | recognition_run_id 链 |
| BI report/dashboard/anomaly/follow-up | Agent Run scope | Agent 工具透传 ctx |
| Agent session/message/command/run | 调用方 ExecutionContext | invoke 参数 |
| 失败 Agent 账本（Run/Work/Evidence/Usage） | 调用方 ctx（先于定义解析） | _record_definition_failure |
| retry / parallel branch / join / timer / approval work | 主 Run scope | workflow runtime ctx |
| finance invoice/line/adjustment | Usage effective scope | 计费排除 effective fixture |

## 6. 查询口径（effective scope）

`effective_scope(row) = row.data_scope ⊕ 父链推导`，父链任意一环为
fixture 且本行 test_run 可归属 → fixture。运营端（首页/列表/汇总/
导出/预算/BI/财务）**默认只展示 effective=operational**；fixture
历史只在"测试与证据中心"显式可见，且必须显示 test_run_id/状态/
数量/作用域/归档时间/完整链路。

## 7. 不可变账本

Usage/Evidence 为 append-only：历史纠偏不改原行，经
`scope_attribution_ledger_v1`（追加式 attribution）计算
effective_scope；所有运营查询与计费消费 effective 口径。

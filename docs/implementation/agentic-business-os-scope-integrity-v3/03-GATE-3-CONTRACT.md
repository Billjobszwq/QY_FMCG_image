# 03-GATE-3-CONTRACT · Gate 3.0 契约

## 状态机（V3 扩展）

```
BLOCKED_BY_SCOPE_INTEGRITY      effective scope 泄漏 > 0（父链口径）
BLOCKED_BY_SCOPE_LINEAGE        binding/test_run/父子一致率 < 100%
BLOCKED_BY_SCOPE_REGISTRY       存在未登记表 / 登记与 schema 不符
BLOCKED_BY_TERMINAL_STATE       terminal Run 下任意层未收敛
                                （run/node/timer/branch/approval/work）
BLOCKED_BY_UAT_FIXTURE_PROJECTION 运营投影含 fixture
BLOCKED_BY_BROWSER_SEMANTICS    浏览器语义断言失败
BLOCKED_BY_GATE_EVIDENCE        证据缺失
STALE_GATE_EVIDENCE             Gate 绑定后代码/数据/证据变化
READY_FOR_REAL_DATA_UAT         全部通过（仅机器可宣布）
```

## 绑定（比 2.1 更全）

1. HEAD、代码树 hash、migration hash（保留 2.1）；
2. **数据库 scope graph fingerprint**：全部 scoped 表行数+
   data_scope/test_run_id 聚合 sha；
3. **Event/Outbox 水位**：event_envelope_v1 max(seq)、
   outbox_v1 pending 计数；
4. **projection hash**：work 投影 hash；
5. **关键表计数**：business_run/work_item/usage/recognition 等。

任一绑定变化 → 旧 Gate 自动 `STALE_GATE_EVIDENCE`。

## 实时性（指令九.4）

- `GET /api/v1/control/gate` 不再只读静态 JSON：实时执行
  freshness 校验（绑定复算）；允许短 TTL 缓存，但 DB 已变化时
  不得继续 READY；
- 全量评估可异步，但 freshness 判定必须同步、便宜（<200ms）。

## Scanner 纪律（指令九.5）

- scanner 遇 表/列/SQL 异常 → 记录并阻断（fail-closed），
  禁止 `except/continue` 放行；
- 扫描器自身被测试用"删列/删表"负例覆盖。

## 检查面（V3 全集）

1. 父子边 scope/customer/project/tenant 一致性（全部边）；
2. fixture effective scope 缺 test_run；
3. operational 页面返回对象逐条无 fixture（API 层探针）；
4. Usage/财务无 fixture（effective 口径）;
5. terminal Run 下 node/timer/branch/work/approval 全收敛；
6. 测试上下文全部 archived；
7. UAT 报告 IDs/Evidence/Usage/Run/Work/trace 可回查；
8. Scope Registry 覆盖率=100%；
9. 保留 2.1 全部检查（HEAD/树/migration/浏览器/服务/integrity/
   CURRENT=prod_v4_best_r1/训练进程=0）。

## 负例清单（至少 12 项，机器可重跑）

媒体泄漏、Work 泄漏、识别泄漏、BI 泄漏、Agent 失败泄漏、Usage
泄漏、节点漂移、静态 Gate 失效（DB 变化后 READY）、未知表、
异常被吞、客户/project 冲突、已归档 test_run 仍可用。

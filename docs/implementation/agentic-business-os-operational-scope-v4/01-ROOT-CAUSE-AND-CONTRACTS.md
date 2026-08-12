# 01-ROOT-CAUSE-AND-CONTRACTS · 根因与 V4 契约

## 1. 根因（为什么 V3 READY 后运营面仍被污染）

1. **IAM 身份无 Test Run 生命周期**：UAT 创建 principal/membership
   时不写 provenance；`archive_namespace` 只收敛业务对象，不收敛
   身份、会话与授权 → 85 active 账号 + 97 授权 + 85 会话残留。
2. **BI 读物理行数**：`/analytics/data-products` 的 `count()` 直读
   `SELECT count(*)` 且 except 吞异常；metric/dashboard 表无 scope
   列 → 物理表覆盖率 ≠ 业务隔离覆盖率。
3. **前端硬编码测试客户**：BI/Usage/Finance/Geo 默认 `uat-cust-a`/
   `demo-cust-a`，真实用户首屏落入测试语境。
4. **Scope Registry 分类逃逸**：global_configuration/reference_registry/
   audit_only 分类默认"不参与扫描"，UAT 在这些面创建的对象永久滞留
   运营平面。
5. **Gate 浏览器覆盖面 < 报告表述**：仅 5 页语义断言，IAM/BI/Finance
   运营面未验证 → 污染可通过 Gate。

## 2. V4 契约

### 2.1 唯一事实源原则
IAM 身份、BI 对象、Finance 上下文的 scope 判定只允许一套结构化
事实源（provenance 列或不可变 binding ledger），禁止多处 LIKE/
硬编码判断；运行时禁止用户名 LIKE 'uat%'。

### 2.2 测试身份生命周期（详见 02）
创建即登记 provenance（test_run_id/data_scope/origin）→ Test Run
归档同事务收敛（principal 禁用/membership 归档/session 失效）→
登录拒绝（稳定错误码+审计）→ 历史只读保留在测试中心。

### 2.3 BI 统一 Query Context（详见 03）
所有 BI 读取必须带 tenant/customer/project/effective scope/time
window/permission/metric version/source evidence；data-products 与
运营 Domain API 强制对账；metric/dashboard/report/anomaly 全部具备
provenance 与归档能力。

### 2.4 Finance 运营上下文（详见 04）
默认客户必须来自 operational customer Domain Service；无客户时诚实
空态；invoice 只消费 effective operational Usage；禁止 UAT/demo
默认值出现在任何请求。

### 2.5 Registry 语义覆盖（详见 05-GATE 与 T5 实现）
每表声明：是否允许 UAT 创建 / provenance / scope 来源 / 父对象 /
effective 查询规则 / 归档规则 / 登录授权影响 / 计费影响 / BI 影响 /
Gate 扫描器 / 浏览器暴露面。

### 2.6 归档与保留
不物理删除任何 principal/membership/usage/evidence/audit；一律
追加式禁用/归档 + 审计。

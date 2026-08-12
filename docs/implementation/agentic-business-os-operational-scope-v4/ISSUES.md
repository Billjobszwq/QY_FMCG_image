# ISSUES · Operational Scope V4

> 格式：`| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |`

| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |
|---|---|---|---|---|---|---|
| SI4-001 | P0 | OPEN | 85 个 UAT principal active + 97 membership（全带客户授权）+ 85 会话未失效；正常 IAM 页直接显示 | before_audit.json iam_* | principal 创建无 provenance；归档不收敛身份 | 迁移 057 provenance 列 + 归档事务 + 登录拒绝 + 历史回绑归档 |
| SI4-002 | P0 | OPEN | data-products 读物理行数（37/25/22/25/50/195/24/20 vs 运营 0/0/0/2/18/…） | before_audit.json bi_dp_* | analytics_api count() 裸 SELECT + except 吞异常 | effective 计数 + 与运营 API 对账 Gate 断言 |
| SI4-003 | P0 | OPEN | bi_metric_v1 含 8+ UAT 指标且无 scope 列；bi_dashboard_v1 无 scope 列 | before_audit.json bi_metrics_* | BI 注册表无生命周期 | 迁移 058 scope 列 + metric 归档 + 列表过滤 |
| SI4-004 | P1 | OPEN | BIWorkbench 默认客户硬编码 uat-cust-a | BIWorkbench.tsx:87 | 硬编码 demo 值 | 默认策略（唯一客户预选/空态/人工选择） |
| SI4-005 | P1 | OPEN | Finance/Geo/Usage 默认客户硬编码 demo-cust-a/uat-cust-a（6 处） | Finance.tsx:26/96、Geo.tsx:73/159/305、UsageWorkbench.tsx:8 | 同上 | 同上 |
| SI4-006 | P1 | OPEN | Gate 浏览器覆盖不足（仅 5 页，缺 IAM/BI/Finance 等 7 页） | si3 browser_evidence.json | 证据面 < 报告表述 | 12 页语义断言 + Gate 覆盖强制 |
| SI4-007 | P1 | OPEN | Scope Registry 分类逃逸（global/reference/audit 未定义 UAT provenance/归档） | scope_registry.py | 物理覆盖 ≠ 生命周期覆盖 | 语义升级：uat_creatable/provenance/archive 等声明 + Gate 检查 |
| SI4-008 | P1 | OPEN | Scope V3 Gate 已 stale（绑定 78f2e990，HEAD 前进） | 实时 /control/gate STALE | 外部 commits | 按指令不重建 READY 掩盖；最终稳定 HEAD 重建证据 |
| SI4-009 | P2 | OPEN | 主管 Agent 浮层 768px 遮挡内容 | QA 报告 P2-001 | fixed 定位无窄屏适配 | 窄屏缩小/可关闭/安全边距 |
| SI4-010 | P2 | OPEN | IAM/BI 列表缺搜索/分页/状态筛选/空载态 | QA 报告 P2-002 | 列表无工具条 | 搜索/分页/筛选/三态 |
| SI4-011 | P1 | OPEN | import_batch_v1 无 scope 列（20 条 UAT 导入批次滞留运营面） | before_audit.json | 表无生命周期 | 迁移 058 scope 列 + 归档 |

（新 Bug 追加 SI4-012+。）

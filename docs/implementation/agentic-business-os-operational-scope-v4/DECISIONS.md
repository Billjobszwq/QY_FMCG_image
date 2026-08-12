# DECISIONS · Operational Scope V4

| ID | 决策 | 理由 | 否决项 |
|---|---|---|---|
| DEC-SI4-001 | IAM 身份用结构化 provenance 列（迁移 057）作为唯一事实源，登录/授权/列表/统计统一消费 | 指令 7.1 只允许一套事实源 | 平行 binding ledger（多处判断漂移） |
| DEC-SI4-002 | 测试账号归档 = 追加式禁用（status=disabled+visibility=history+archived_at），会话注销属运行时安全失效；principal/membership 行永不物理删除 | 红线：不删历史 | 物理 DELETE |
| DEC-SI4-003 | data-products 与 BI 全部读取走统一 effective 计数函数，并与运营 Domain API 逐项对账进 Gate | 物理行数已证伪 | 各报表自拼 SQL |
| DEC-SI4-004 | Agent BI draft 无明确 customer/project 时只生成命令预览不落库 | 指令 8.4 | 默认落测试客户 |
| DEC-SI4-005 | 前端默认客户一律来自 operational customer 服务；无客户时空态 + 导入入口；删除全部硬编码 | 指令 9.1/9.2 | UI 隐藏但 API 仍发测试客户 |
| DEC-SI4-006 | Registry 从表覆盖升级为对象生命周期覆盖：每表声明 uat_creatable/provenance/archive/login/billing/bi/browser 影响 | 指令十 | 以分类豁免扫描 |
| DEC-SI4-007 | 修复期间不重新生成 READY；最终 READY 仅在稳定 HEAD + 全量证据重建后由机器评估给出 | 指令 P1-005 | 重跑 gate 掩盖 |
| DEC-SI4-008 | 历史 85 账号按已登记 registry namespace 一次性回绑 provenance 后统一归档，审计入账；运行时禁止名称判断 | 指令 7.1/十八 | 运行时 LIKE 'uat%' |
| DEC-SI4-009 | 浏览器验收固定 12 页 × 四视口清单，Gate 强制覆盖；语义断言含 input 默认值与请求 URL | 指令 11.4 | 只截图 |

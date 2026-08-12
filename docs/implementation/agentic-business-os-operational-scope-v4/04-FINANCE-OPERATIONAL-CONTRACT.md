# 04-FINANCE-OPERATIONAL-CONTRACT · Finance/Usage 运营上下文

## 1. 默认值清除

- 删除 Finance/Usage/Geo 页面全部 `uat-cust-a`/`demo-cust-a`
  硬编码（7 处），默认客户必须来自 operational customer Domain
  Service；API 请求也不得携带测试默认客户。
- 无真实客户时：Usage"暂无运营客户"；Contract"请先创建客户"；
  Invoice 不得生成测试账单；CSV 导出不得默认导出测试账本。

## 2. Usage 与 Billing（延续 V3 口径）

- 不修改不可变 Usage 原行；effective scope = attribution ⊕ 父 Run
  ⊕ 父客户（usage_api `_EFFECTIVE_OP`）。
- invoice 只消费 effective operational Usage；legacy unattributed
  单独展示、不自动计费；账单可下钻 Run/Evidence。

## 3. Gate 断言（3.1 新增）

- fixture effective usage in operational finance = 0
- invoice lines derived from fixture usage = 0
- default finance customer fixture token = 0（前端源码静态 + 浏览器
  input/select 默认值 + 实际请求 URL 三重断言）

## 4. 界面

- Finance/Usage 客户选择器来自 `/master/customers`（operational）。
- 空态提供"先创建/导入客户"入口；加载/错误/空三态诚实。
- 人工备用入口始终可用（不依赖 Agent）。

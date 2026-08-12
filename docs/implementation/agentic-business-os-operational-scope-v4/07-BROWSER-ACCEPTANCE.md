# 07-BROWSER-ACCEPTANCE · 浏览器验收（12 页 × 四视口）

## 1. 覆盖页面（Gate 强制，少一页不过）

home、data/import、survey/design、geo/addresses、vision/recognize、
analytics/reports、workflow/studio、iam/accounts、master/customers、
finance/contracts、help、status

## 2. 语义断言（不只截图）

- 每页 DOM fixture token 数 = 0（uatv*_/UAT V*/uat_fixture/测试客户
  等真实文本匹配）
- analytics/iam/finance 额外：API 返回对象数量、input/select 默认值
  （不得为 uat-cust-a/demo-cust-a）、active UAT identity 数量、
  BI data-product 与运营 API 对账、Finance 实际请求 URL
- console 登录后清空再收集，unexplained = 0；network 4xx/5xx 记录

## 3. 四视口（1440/1280/1024/768）

- 无横向溢出（双采样）
- 主管 Agent 浮层不遮挡表格/分页/提交按钮/底部最后一条数据；
  有安全边距；键盘可聚焦；aria-label；可关闭/缩小；不影响滚动
- 关键列表具备搜索/分页/筛选且真实可用

## 4. 诚实界面（运营客户 = 0 时）

客户页 0、BI 数据产品客户行 0、BI 不显示测试客户、Finance 不预填
测试客户、首页不伪造业务量、提供"导入真实客户"入口。

## 5. 证据格式

`.eval/scope_v4/browser/browser_evidence.json`：pages[] 含 route/
viewport/expected/actual/assertion/screenshot/sha256/console；
Gate 的 browser_semantic_assertions 与 viewports_covered 消费。

# 06-UAT-V6-PROTOCOL · UAT V6 协议

## Namespace

`uatv6_<UTC时间>_<随机短码>`；先建 Test Run 上下文，再创建任何对象。

## 新增验收（在 V5 全领域链之上）

### IAM
- 六角色：owner/project manager、field worker、survey designer、
  analyst、finance、auditor（创建时携带 test_run_id）
- Test Run 期间按作用域登录成功；跨客户 403；越权写 403
- **归档后全部登录失败**（负例实测）；principal/membership 历史
  仍在测试中心；正常 IAM 页面不显示

### BI
- 创建测试 metric/dashboard/report/anomaly + Agent BI draft
  （全部携带 test_run）
- Test Run 期间仅测试上下文可见；不进运营 BI；不影响 data-product
  operational count；归档后历史保留但不进运营页面

### Finance
- fixture Usage、fixture rate calculation、fixture invoice dry-run
- 不进运营客户 Usage、不进正式 invoice、不影响 operational budget；
  测试中心可下钻 Run/Evidence

### 原有全领域链（继承 V5）
客户/项目/SKU/员工/地址/坐标/路线/围栏/差旅/全问卷题型/跳题 DAG/
自动评分/门头负例正例/V4 Best 识别 suggestion/人工 final/Workflow
全节点/Agent BI/异常追问/真人回答/报告新版本/Usage/Evidence/六角色/
跨客户隔离/归档/测试中心历史。

## report.json IDs（全部非空）

V5 的 24 键 + 新增：principals（6）、memberships、metric、
dashboard、finance_dry_run_invoice、rate_calc。validator 对缺失
fail-closed。

## 归档断言

- active UAT principals = 0；operational UAT memberships = 0
- archived identity 登录成功 = 0
- 运营首页/IAM/BI/Finance fixture token = 0
- 测试中心全历史可查

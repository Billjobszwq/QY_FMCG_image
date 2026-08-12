# 05-GATE-3.1-CONTRACT · Gate 3.1

保留 Gate 3.0 全部绑定（HEAD/代码树/迁移/DB fingerprint/freshness
实时复评），新增以下检查与状态：

## 状态机新增

```
BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE   IAM/BI/Finance 运营面 fixture 暴露
BLOCKED_BY_IAM_IDENTITY                  active UAT 身份/授权/会话 > 0
BLOCKED_BY_BI_EFFECTIVE                  BI 物理 vs effective 对账失败
BLOCKED_BY_FINANCE_CONTEXT               Finance/Usage 测试默认值/fixture 计费
```

## 新增检查

### IAM
1. active UAT principal = 0（结构化 provenance 判定，非名称）
2. operational UAT membership = 0
3. archived Test Run principal 登录被拒（负例实测）
4. IAM API 默认结果 fixture = 0
5. IAM 页面 fixture token = 0（浏览器）

### BI
6. UAT metric operational = 0
7. UAT dashboard operational = 0
8. UAT report operational = 0
9. data-products 计数与运营 Domain API 逐项一致
10. Agent BI 查询不读 fixture
11. BI 页面 fixture token = 0（浏览器）

### Finance
12. 默认客户不含 UAT/demo（源码静态 + input 默认值 + 请求 URL）
13. Finance/Usage fixture effective rows = 0
14. invoice fixture usage = 0

### Registry / 浏览器 / freshness
15. Registry 语义覆盖（UAT provenance/归档规则声明）= 100%
16. 浏览器覆盖 12 个一级工作台（少一页即 Gate 不过）
17. HEAD 变化 → STALE；DB fingerprint 变化 → STALE（保留）
18. scanner 表/列异常 fail-closed（保留）
19. UAT V6 IDs 缺失 → BLOCKED

## 负例清单（≥20，见 gate_negative_tests_v4.json）

active fixture principal / fixture membership 进运营 / archived
登录成功 / UAT metric 进运营 BI / UAT dashboard 进运营 /
data-product raw≠effective / BI 默认 UAT 客户 / Finance 默认
UAT/demo 客户 / fixture Usage 进预算 / fixture Usage 进 invoice /
Registry global 逃逸 / analytics 页 fixture token / IAM 页 fixture
token / Finance 页 fixture token / 浏览器只查四页 / HEAD stale /
DB stale / scanner 异常 / V6 IDs 缺失 / 浮层遮挡。

## 重建规则

修复期间不得重新生成 READY 掩盖问题；最终 READY 必须在稳定 HEAD 上
重建全量证据（测试/UAT V6/浏览器 12 页/对账）后才允许。

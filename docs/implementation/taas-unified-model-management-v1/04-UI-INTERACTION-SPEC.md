# 04｜系统级模型管理 UI 规范

## 1. 产品位置

新增桌面一级模块：

```text
group: models
label: 模型管理
window title: 模型管理
required scope: models.config.read 或 models.usage.read
```

它与“主管 Agent”“智能识别”“数据与资产”等并列。无权限时：

- 桌面不显示图标；
- 不创建窗口；
- 路由/快捷调用不泄漏资源；
- 后端仍执行IAM，不依赖前端隐藏。

## 2. 兼容现有视觉系统

必须复用：

- `DemoDesktop`、`DesktopIcon`、`AppWindow`、`ModuleWorkbench`；
- `PageHeader`、`ApiTable`、`StatusBadge`、`KV`、`ErrorState`、`NeedLoginState`；
- `Button`、`Input`、`Select`、`HedgehogLoader`；
- 现有design tokens：奶油背景、surface、橄榄墨色、交互态品牌橙、8px窗口圆角。

禁止新增传统管理后台侧栏、另一套颜色、渐变、毛玻璃、巨型卡片或假数据Dashboard。

## 3. 模块标签

### 3.1 连接管理 `/models/connections`

PageHeader：

- 标题：连接管理
- 描述：统一管理本地与外部模型服务；仅授权角色可见
- 操作：刷新、新增连接

表格列：名称、位置、协议、Base URL、凭据状态、健康、Active版本、操作。

“新增/编辑”打开受控子窗口，字段：

```text
连接名称
本地 / API
Provider模板
Base URL
API Flavor
API Key（password，只写）
Timeout
Max retries
```

按钮顺序：保存草稿、测试连接、申请启用。测试成功不得改变active状态。

### 3.2 模型目录 `/models/catalog`

表格列：模型ID、Connection、Capabilities、Revision、Embedding dimension、来源、Probe状态、最近验证。

支持“发现模型”和“人工登记”。不得根据模型名自动判定能力；能力徽章只显示probe通过项。

### 3.3 能力分配 `/models/bindings`

筛选：对象类型、租户/客户/项目、Capability、状态。

表格列：对象、能力、Connection/Model、来源、作用域、版本、状态、操作。

编辑窗口必须展示影响预览：受影响模块/Agent、索引重建、预算变化、fallback、回滚目标。Agent行明确显示`source=Agent Definition`。

### 3.4 运行治理 `/models/governance`

顶部只显示必要指标：requests、tokens或诚实替代单位、p95、错误率、预算。下方为：

- 用量趋势；
- Provider/Model健康表；
- 告警；
- 待审批；
- Active/Canary/历史版本；
- 审计下钻。

默认不把普通员工个人数据跨scope聚合。财务只见成本/Usage，不见Connection Secret元数据。

### 3.5 本地模型 `/models/local`

迁移当前`frontend/src/pages/vision/Models.tsx`的训练门禁、驻留和legacy表格。读取原API，不复制后端事实源。旧`/vision/models`映射到此标签。

## 4. 状态文案

统一状态：

| 状态 | UI |
|---|---|
| draft/未配置 | neutral |
| testing/pending_approval/canary | warn |
| ready/active/healthy | good |
| rejected/failed/unavailable/metering_incomplete | serious |
| degraded | warn，必须显示原因 |

禁止只用颜色表达状态。

## 5. 错误与空态

- 401：`NeedLoginState`。
- 403：显示“无模型管理权限”，不显示资源数量。
- 404：显示“资源不存在或不可见”。
- 409：显示版本冲突并提供刷新，不覆盖用户草稿。
- 422：字段级安全错误，不回显Secret。
- 429：显示平台配额或Provider限流及Retry-After。
- 503：显示Provider/SecretStore不可用及稳定错误码。
- 空表：诚实显示“暂无连接/模型/绑定”，不得填充示例数据。

## 6. 前端权限投影

前端使用现有`/api/v1/iam/whoami` scopes：

- `ModuleGroup`增加可选`requiredScopes`；
- Desktop只渲染至少命中一个required scope的group；
- 无权限route alias请求不打开窗口；
- 刷新或会话切换时重新获取whoami；
- 网络失败时fail-closed隐藏受限模块。

UI权限只改善体验；所有API仍独立鉴权。

## 7. 浏览器验收

在1024、1280、1440宽度验证：

- 模型管理员可见独立图标和五个标签；
- 普通员工无图标、无窗口、直接API为403；
- 表格和编辑子窗口无溢出；
- API Key保存后不可回显，DOM和网络响应无密钥；
- maker看不到批准自己变更的可用动作；
- 409不丢草稿；
- 429、503、degraded与empty状态真实；
- 智能识别不再显示系统级模型管理标签；
- `/vision/models`兼容打开`/models/local`；
- 无样本/假数据。

# 真实数据端到端 UAT

## 目标

用户下一轮将导入真实地址、真实客户并从空白配置真实问卷。本轮实施 Agent 必须先用明确标记的 `uat_fixture_v3` 完成同路径机器预演，保证用户不需要终端或直接操作数据库。

## 角色

- Platform Owner：建角色、客户、项目、Agent 和工作流；
- Project Manager：建问卷、导入地址、规划任务、看进度；
- Field Worker：看日程、到店、填写问卷、拍照；
- Analyst：建指标、Dashboard 和异常追问；
- Finance：查看客户 Usage；
- Auditor：只读查看事件、证据和版本。

## 场景

### 1. 初始化

1. Owner 登录首页，看到真实 Dashboard、服务状态和空的 UAT 项目进度；
2. 在账号权限中复制角色并调整权限，使用权限模拟器验证；
3. 从 Import Center 下载客户、项目、SKU、员工、地址 CSV/XLSX 模板；
4. 分别上传 fixture，执行 dry-run、修复至少一条故意错误、提交；
5. 在主数据页面看到新客户/项目/SKU/员工/地址及导入证据。

### 2. 地址与外勤

1. 选择缺坐标地址，点击“获取坐标”；
2. 有 Provider 时获取候选并确认；无 Provider 时导入经纬度并显示配置提示；
3. 在地图看到门店点、员工起点、未分配任务；
4. 设置时间窗、容量、区域和费用规则，生成路线；
5. 人工拖动调整一站并保存新版本；
6. 发布外勤任务，员工日历出现安排。

### 3. 自定义问卷

1. 从空白创建问卷；
2. 加入客户、项目、SKU、单选、多选、填空、打分、拍照题；
3. 配置一条跳题逻辑、一项自动评分和一项门头照必选；
4. 移动端预览、测试填写、lint、批准、发布；
5. 将问卷分配给外勤任务。

### 4. 可视化工作流与 Agent

在 React Flow 画布拖出并发布：

```text
项目启动 → 生成外勤任务 → 等待到店/围栏
→ 填写问卷 → 照片质量门 → V4 best 识别建议
→ 人工确认 → 响应入库 → BI 刷新
→ 异常判断 → Analytics Agent 追问/人工回答
→ Usage 记账 → 完成
```

必须包含 condition、wait、parallel/join、human approval、agent、model/capability 和失败人工接管节点。

### 5. 识别与人工确认

1. Recognition 页面默认选择 V4 best；
2. 用户上传问卷照片并看到真实框、SKU、置信度、耗时、profile、trace、evidence、usage；
3. 低置信结果进入人工确认，不阻断整个问卷；
4. 其他模型 Profile 可选择时真实运行，不可用时显示 blocker 和诊断；
5. 从任务详情打开 Label Studio/审核入口并返回；
6. 训练中心选择一个数据集执行 dry-run/preflight，但不启动长训练。

### 6. BI 与 Usage

1. Analyst 注册问卷响应数据产品；
2. 创建一个计数指标、一个平均分、一个通过率和一个受限计算字段；
3. 拖拽至少三种图表到 Dashboard，按客户/项目/区域过滤；
4. 制造一条异常，Agent 生成追问，人工回答后报告形成新版本；
5. Finance 查看该客户的 storage/photo/model/token Usage，逐条下钻到同一 run/evidence；
6. 导出 Usage CSV。

### 7. 首页闭环

返回首页后必须看到：

- 项目进度已更新；
- 日历中的外勤任务已完成；
- 当前待办只剩真实未完成项；
- 活动日志出现导入、发布、到店、问卷、识别、报告和 Usage；
- Supervisor 能回答“项目做到哪里、哪个地址失败、用了哪个模型、花了多少 Usage”，并给出证据链接；
- Auditor 能只读查看完整链路，不能修改。

## 自动验收对账

必须生成一个不可手填的 reconciliation 报告，至少包含：

- customer/project/workflow/run/work/schedule/field/survey/response/photo/recognition/report/usage/evidence ID；
- DB/API/UI/Agent 四方状态；
- 权限矩阵结果；
- 事件序列和 current projection；
- 每个模块人工入口和 Agent command；
- 数据/制品/定义 hash；
- 浏览器截图和 console；
- 性能、安全、恢复结果。

只有全部一致才允许机器 Gate 进入 `READY_FOR_REAL_DATA_UAT`。


# 03 · UAT V2 协议

执行脚本：`scripts/v3_uat_rehearsal_v2.py`（不覆盖旧 v1 报告，v1 保留为
历史 smoke evidence）。输出目录：`.eval/v3_uat_v2/`。

## namespace

每次运行生成 `uatv2_<timestamp>_<random>`，所有实体 ID 前缀化：
customer=`{ns}_cust`、project=`{ns}_prj`、sku=`{ns}_sku`、
employee=`{ns}_emp`、user=`{ns}_pm` 等。任何实体返回
`inserted=0/skipped=1` 该步判失败（validator `check_created`）。

## 六角色（真实登录会话）

| 角色 | 用途 |
|---|---|
| Platform Owner(bill) | 建角色/客户/项目/切模授权 |
| Project Manager `{ns}_pm` | 导入、问卷、路线、进度 |
| Field Worker `{ns}_fw` | 领取任务、上传门头照、填写 |
| Analyst `{ns}_an` | BI 指标/图表/Dashboard/异常 |
| Finance `{ns}_fin` | Usage 下钻/导出 |
| Auditor `{ns}_aud` | 只读验证（写操作必须 403） |

跨客户 403、Auditor 只读、最后管理员保护、Agent allowlist 约束均实测。

## 问卷（全部题型真实使用）

客户题/项目题/SKU 题（source 绑定）、单选、多选、填空、打分、matrix、
description、跳题、自动评分、门头必拍（真实上传门头照，无照片提交必须
失败一次作为负证据）、商品照片识别（v4_best_standard）、人工确认
（accept/modify 分开记录）。

## 工作流（完整业务流）

项目启动→生成外勤任务→等待到店(wait)→填写问卷→照片质量门(condition)→
V4 识别建议(capability)→人工确认(human_approval)→响应入库→BI 刷新→
异常判断(condition)→Analytics Agent 追问(agent)→人工回答→Usage 记账→
完成。覆盖：condition/wait/parallel+join/loop/human approval/agent/
capability/失败重试/人工接管/暂停/恢复/取消。

## 报告必填字段（validator 强制）

所有业务 ID；customer/project/tenant 关系；run/work/branch/agent/
recognition/report/usage/evidence 关系；每步 API 状态；DB 投影状态；
UI 对象链接；权限矩阵；事件序列；hash；浏览器截图路径；console；
p50/p95；重启恢复结果；失败与人工接管证据。缺一即报告判 FAIL。

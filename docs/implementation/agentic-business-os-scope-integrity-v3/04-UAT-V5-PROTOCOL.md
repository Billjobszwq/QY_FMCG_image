# 04-UAT-V5-PROTOCOL · UAT V5 全领域链协议

## Namespace

`uatv5_<yyyymmddHHMMSS>_<6位随机>`，唯一不复用；先建 Test Run
上下文（`POST /api/v1/test-data/run`），其后一切对象携带或继承
该 test_run_id。

## 领域链（必须全部走通，且每步记录对象 ID）

1. Test Run 上下文（namespace + fixture customer/project）；
2. 客户、项目、SKU、员工、地址（全部同事务 scope）；
3. 地址坐标（含手工坐标降级）、外勤任务、路线、围栏、差旅；
4. 问卷：客户/项目/SKU 引用、单选、多选、填空、打分、matrix、
   description、跳题 DAG、自动评分；
5. 门头契约：负例（非门头拒绝）→ 上传真实门头 → 成功；
6. 货架照片 → V4 best 识别 suggestion → 人工 final；
7. 工作流：trigger/transform/condition/wait/parallel/join/loop/
   approval/agent/command；
8. Agent 创建 BI 草稿（继承 Run scope）；
9. 异常 → Agent 追问 → 真人回答 → 报告新版本；
10. Usage/成本链可下钻；fixture 不进运营计费；
11. 失败 Agent 账本完整且保持 fixture；
12. 六角色权限矩阵 + 跨客户 403。

## report.json 强制字段

`ids` 必须非空且覆盖：test_run、customer、project、sku、employee、
address、field_task、route、geofence、travel、survey、assignment、
response、media（负例+正例）、workflow_def、run、work、timer、
branch、approval_work、agent_run、agent_failed_run、bi_report、
anomaly、followup、recognition_task、evidence、usage、trace。
validator 对 ids 完整性 fail-closed（缺失即 FAIL）。

## 验收断言

- 进行中：普通首页/客户/问卷/识别/BI/Usage/任务板 fixture=0；
- 归档后：全 Domain effective fixture 泄漏=0；
- 测试中心可查全部 fixture 历史（test_run_id/状态/数量/作用域/
  归档时间/链路）；
- 泄漏注入负例：改 DB 制造一条泄漏 → Gate 立即 STALE/BLOCKED →
  修复并重跑证据后才允许 READY。

## 禁止

导入用户正式数据；切换生产模型；启动长训练；用名称 LIKE 运行时
识别 fixture；用 UI 隐藏代替后端隔离。

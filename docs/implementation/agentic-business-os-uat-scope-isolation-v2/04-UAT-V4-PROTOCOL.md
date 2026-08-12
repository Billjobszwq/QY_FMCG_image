# 04-UAT-V4-PROTOCOL · UAT V4 机器预演协议

## Namespace

`uatv4_<yyyymmddHHMMSS>_<6位随机>`，全新唯一，不复用历史。

## 顺序契约（P1-001 修复核心）

1. 先经测试数据 API 创建 **Test Run 上下文**
   （`POST /api/v1/test-data/run`：namespace + fixture customer/project）；
2. 之后所有对象（SKU/employee/address/field task/route/survey/
   response/media/workflow run/agent/recognition/usage/evidence/BI）
   都携带该 test_run_id 创建，或从父对象继承；
3. 禁止"先创建后按名称补标"。

## 必贯通场景

fixture customer/project/SKU/employee/address、手工坐标/降级
geocoder、field task、route、survey（全题型）、门头契约
（负例+正例）、response/media、workflow（wait/parallel/join/loop/
human_approval/command/model/agent）、V4 recognition、evidence、
usage、BI anomaly、Agent follow-up、human answer、report v2、
失败 Agent 账本、retry、cancellation、restart recovery。

## 验收断言

- 所有对象 test_run_id 完整率=100%；
- 父子 scope 一致率=100%；
- UAT 进行中：普通首页 0 fixture；仅测试中心可见；
- 归档后全 Domain operational fixture 泄漏=0；
- 测试中心仍可查全部历史证据。

## 禁止

导入用户正式数据；切换生产模型；启动长训练。

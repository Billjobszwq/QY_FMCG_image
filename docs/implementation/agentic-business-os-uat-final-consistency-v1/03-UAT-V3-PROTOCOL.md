# 03 · UAT V3 协议

脚本 `scripts/v3_uat_rehearsal_v3.py`；输出 `.eval/v3_uat_v3/`
（report.json / gate.json / browser/）。V2 报告保留。

主工作流（识别必须在工作流内，继承 parent_run/correlation/customer/
project/node/branch/evidence/usage）：
项目启动→外勤任务→等待到店(wait)→填写问卷(condition)→照片质量门→
model/capability 调用 V4 识别→识别建议→人工确认(human_approval)→
响应入库→BI 刷新→异常检测(anomaly hit=true)→Analytics Agent 追问→
人工回答→报表新版本→Usage 记账→完成。
覆盖：trigger/transform/condition/wait/parallel+join/loop/
human_approval/agent/model/失败重试/人工接管/取消/Evidence/Usage。

终态断言：批准→run succeeded+主 work done+approval done；
拒绝→run cancelled+approval cancelled(rejected)；
取消并行 run→分支/主 work 全 cancelled 且不被后台线程回写；
fixture 归档后 operational current 残留=0；Gate 自动计算。

# 00 · 现场审计（UAT Final Consistency v1）

审计时间：2026-08-12。HEAD `6cbca9c0`（与指令预期一致，无增量）。
四服务 UP；prod_v4_best_r1；detector `84bf993618937700…`；无训练进程。

## 已复现的终态漂移（DB 事实）

1. **cancelled run 主 WorkItem 未收敛（4）**：
   - run-5be533c2e28e → work 状态 waiting
   - run-df31c2f6b8a3 / run-1d87e49e98f7 / run-c858ce98a621 → running
   取证（run-df31c2f6b8a3）：07:30:20 started+parallel_started；
   07:30:22 run cancelled；**07:30:40 后台线程仍发出
   parallel_joined**（无取消检查），随后尝试 succeeded 被状态机拒绝，
   清理中断；事件流无 run.cancelled 终态事件 → reconcile/projection
   按事件把 work 推回 running（drift_fixed 反向回退终态）。
   work-893a20140baf updated_at 09:05:08（重启/reconcile 时段）。
2. **succeeded run 残留 approval 子待办（3）**：
   run-a8984d09e2e3/work-29851415f227、run-f0529cac44db/work-540a9eb7a9db、
   run-6e7fdeec3123/work-b48d374d735b（均"UAT2 人工确认识别结果"）。
   approve_run 批准路径从不关闭 approval WorkItem。
3. **首页投影被污染**：/api/v1/home/dashboard todos=
   {running:3, waiting:1, blocked:3, approval:3}——全部为上述漂移残留。
4. **Agent 失败账本为 0**：command_kind='agent.invoke' AND
   status='failed' → 0 行。invoke 在定义校验失败时于创建 run 之前抛
   409（runtime.invoke 首部 raise AgentRuntimeError）。
5. **UAT fixture 污染主数据**：md_customer_v1 含 15 个 uat* 客户
   （uat-cust-a/b、uat_fixture_v3_*、8 轮 uatv2_* namespace），
   无结构性隔离字段；其 run/work 进入运营投影。
6. **Gate 非证据驱动**：evaluate_gate() 仅接收调用方手写布尔；
   仓库无任何从 report/DB/测试/服务/浏览器自动计算 Gate 的路径。
7. **UAT V2 主工作流无 model/capability 节点**：识别在工作流外单独
   调用；anomaly 链 hit=false/anomaly=None，仅验证 HTTP 无错误。

## 根因（待红测试固化）

- RC-A cancel_run 不发终态事件、不关 approval/timer/branch；
- RC-B 后台分支线程/inline wait 无取消检查，取消后继续执行；
- RC-C 各完成路径直写终态，无统一 CAS/finalize，无法保证关联对象收敛；
- RC-D approve_run 批准不关闭 approval WorkItem；拒绝仅映射 cancel；
- RC-E projection/reconcile 的 drift 修复可把终态 work 回退为活动态；
- RC-F Agent 定义校验先于统一调用链（无失败 run/evidence/usage）；
- RC-G fixture 无 data_scope/visibility 结构隔离；
- RC-H Gate/validator 接受手写布尔与宽松校验。

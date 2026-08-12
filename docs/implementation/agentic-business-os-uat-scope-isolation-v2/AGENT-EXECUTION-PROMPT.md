# AGENT-EXECUTION-PROMPT · UAT Scope Isolation V2

本轮执行提示词 = 用户 2026-08-12《UAT Fixture 全域隔离、执行作用域
贯通与可信 Gate V2 最终纠偏指令》。要点固化如下（全文以用户指令为
准）：

1. 持续执行 T0→T10，不在阶段间询问用户；仅外部阻断可停。
2. 开工前 Gate 必须降级为 BLOCKED_BY_UAT_FIXTURE_PROJECTION。
3. 架构：统一 ExecutionScopeV1（tenant/customer/project/data_scope/
   test_run_id/correlation/parent_run/actor/source/created_at），
   服务端解析，fail-closed 继承；唯一事实源；禁止名称模式运行时依赖。
4. T1 先写 ≥22 红测试并保存结果；T2 scope 模块；T3 迁移+backfill
   （备份、幂等、追加式、unresolved 隔离）；T4 全 Domain 默认
   operational；T5 测试与证据中心；T6 Gate 2.1（≥25 检查 + HEAD/树
   hash 绑定 + STALE）；T7 浏览器语义证据；T8 UAT V4（先 Test Run
   后对象）；T9 前端拆包（初始 gzip<500KB）+ 警告收口；T10 回归、
   服务恢复、12 项 Gate 负例、最终报告 57 项。
5. 安全：不 merge/push/deploy；不切生产模型；不启动长训练；不删
   历史资产；迁移前备份；小步提交；8091/8092/8300/8400 保持可用。
6. 完成条件 23 项硬门槛全部满足才可输出 READY_FOR_REAL_DATA_UAT；
   否则诚实输出 BLOCKED。

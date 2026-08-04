# Platform V2 — ACCEPTANCE

> 每个里程碑按手册 §3.1 的 8 项逐一验收；全部通过才能勾选 PLAN 中对应里程碑。

## 每里程碑通用验收 8 项（手册 §3.1）

1. 可见 URL（可浏览器打开）
2. API/CLI 可调用（真实命令+退出码）
3. 真实流程执行（非 mock 数据）
4. 状态真实（healthy/degraded/unavailable，不谎报）
5. 测试通过（新增测试 + 全量回归）
6. 证据留存（截图/日志/制品路径入 EXECUTION-LOG）
7. 回滚说明
8. 8091/8092 不受影响证明

## M1 验收矩阵

| 项 | 验收标准 | 结果 |
|---|---|---|
| URL | http://127.0.0.1:8400 可打开 Web Shell | ✅（HTTP 200，Chrome headless 截图 /tmp/pv2_evidence/m1_overview.png） |
| Health | `/api/v1/health` 返回各服务状态，8300 DOWN 时标 degraded | ✅（degraded；8091/8092/8455 healthy，8300/8301 unavailable） |
| 页面 | 七页骨架全部可导航 | ✅（6 张截图：overview/runs/recognition/annotation/training/status） |
| E2E | 浏览器截图证据 | ✅（/tmp/pv2_evidence/m1_*.png；识别 bridge 真实样本 count=2） |
| 真实流程 | 非 mock：真实上传图片经 8400 bridge 调 8091 返回真实识别结果 | ✅（36619578.jpg → count=2，run_id 真实） |
| 状态真实 | healthy/degraded/unavailable 不谎报 | ✅（8300/8301 未启动 → unavailable；平台级 degraded） |
| 回归 | 170+ 新测试全绿 | ✅（**198 passed in 2.97s**，exit 0） |
| 回滚 | 删除 8400 进程即回滚，不影响旧服务 | ✅（8400 独立进程；8091 bundle 未动、8092 正常） |

## M2 验收矩阵

| 项 | 验收标准 | 结果 |
|---|---|---|
| Registry | 模块经 Manifest 注册；依赖方向测试证明 platform 不 import modules | ✅（test_m2_registry.py：重复注册/缺 adapter 拒绝；AST 守卫全绿） |
| 契约 | Asset/Evidence/Audit/Usage/Job 契约有 fixture+版本+破坏性变更测试 | ✅（CONTRACT_VERSION=1.0.0；extra=forbid 拒绝未知字段） |
| Adapters | legacy.recognition.v2 / legacy.training.monitor 注册成功并报告健康 | ✅（/api/v1/capabilities 返回 2 项；m2_status.png 渲染；8091/8092 healthy） |
| 存储 | PlatformStore migration 可执行，备份可校验 | ✅（20 个 store 测试：防篡改+integrity_check+重启恢复） |

## M3 验收矩阵

| 项 | 验收标准 | 结果 |
|---|---|---|
| 真实流程 | 上传真实照片 → CAS → 质量 → 8091 识别 → 人工门 → EvidenceBundle → Usage/Audit → RecognitionResult | ✅（run ab0946f5：36619578.jpg → sha edf07854 → 真实识别罐装雪碧330ml 0.9996/2L七喜 0.6439；evidence=1；gate.approved+run.completed 审计落库） |
| 持久化 | Run/NodeExecution/Checkpoint 重启后可恢复查询 | ✅（重启 8400 后 GET /api/v1/runs count=2） |
| waiting_human | 人工门真实暂停，批准后继续 | ✅（ab0946f5 waiting_human → approve → completed；拒绝为终态有测试覆盖） |
| 幂等 | 重试不重复识别/不重复 Usage | ✅（rec.calls==1 恢复后不重识别；同 idempotency_key 不产生新 run；usage 恰 1 条） |
| 非识别 Graph | system_health_v1 完整运行，Kernel 无 FMCG 特例 | ✅（真实探测 completed：total=5、unhealthy=[label_studio, ml_backend]、overall=degraded） |
| 版本化 | GraphDefinition 修改必须新版本，原地改被拒绝 | ✅（同名同版本内容哈希不同 → GraphVersionError，test_graph_kernel.py） |
| 节制 | 最大节点数/循环数/超时/预算触发生效 | ✅（max_nodes/max_loops→BudgetExceeded、timeout_s→run failed，均有测试） |
| E2E | 浏览器走完整流程并截图 | ✅（Chrome headless /tmp/pv2_evidence/m3_runs.png：两条真实 completed Run + 节点时间线渲染） |
| 最终报告 | 按手册 §14 输出，含三冻结值 | ⏳（第一阶段任务结束时输出；当前 production_switch=false、training_started=false、deleted_files=false） |

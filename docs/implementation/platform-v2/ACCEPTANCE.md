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

## M4 验收矩阵

| 项 | 验收标准 | 结果 |
|---|---|---|
| LS 启动 | 修 start_label_studio.sh 路径；项目内数据目录 + 8300 固定 | ✅（1.23.0 sqlite；/health 200；`.label-studio/` 项目内） |
| 项目/任务/prediction/annotation 同步 | 平台创建/导入/同步；对账 API | ✅（batches API + reconcile；LS API 为事实源） |
| assisted/blind 分离 | 盲标者不可见 prediction | ✅（trial10：assisted preds=9 / blind=0；trial50：9/0；reconcile blind_no_predictions=true；TDD 红线测试） |
| webhook inbox 去重 + 对账 | 不依赖 webhook 单点成功 | ✅（(source,event_id) UNIQUE；重放 accepted=false；真实 LS 投递接收；trial50 webhook 未达仍 consistent） |
| 全保留 | 自动框/人工初稿/二审/仲裁/最终框 | ⏳（prediction 已保留；人工环节待授权） |
| 错标统计 | — | ⏳（依赖人工标注数据，待授权） |
| 分享链接 scope/有效期 | — | ⏳（LS 原生 share 未启用外部账号，待授权场景） |
| 不可变 truebox manifest 导出 | — | ⏳（annotation 产生后导出；待授权） |
| 10→50 张 | 先 10 张 E2E 再扩 50 张；不直接 2300 | ✅（f155180f 10+10 / 334dd7fc 50+50；真实 8091 预标注） |
| 用户可见 | 工作台创建试验项目 → LS 标注 → 回平台看状态/导出 | ✅（标注审核页：batches/创建/导入/对账/inbox；截图 /tmp/m4_annotation*.png） |

## M5 验收矩阵

| 项 | 验收标准 | 结果 |
|---|---|---|
| DatasetSnapshot 契约 | split guard（train/val sha256/store/session 零交集）+ manifest hash + 人工审核来源字段 | ✅（泄漏 manifest 拒注册；hash 确定性；TDD 3+2 测试） |
| truebox 评估修正 | 真实 FP/photo 预算扫描 + 互斥错误账本；TopK 不得用于晋级 | ✅（promotion_gate：recall@FP1/FP3 IoU0.5 + FP/photo；TDD pass/fail） |
| 统一推理导出/评估 | E0/P0/P1 同一 GT 统一评估；导出 manifest 缺文件 fail-closed | ✅（unified_eval + export_inference_manifest TDD） |
| dry-run | 只产计划不执行；展示命令/MPS G0/算力预算/停止线 | ✅（dry-run 3d3560b5 命令回显；授权状态不变） |
| 训练启动授权门 | flag training_authorized + IAM admin 双校验 | ✅（无授权 start 403；operator 授权 403；admin 授权 200） |
| 发布分离 | 训练完成仅 candidate；发布独立 admin 审批；禁 auto_switch | ✅（非 candidate 拒批；operator 拒批；TDD 全链路） |
| 用户可见 | 训练页显示"为什么不能训练、还差什么、批准后将运行什么命令" | ✅（gates banner + reasons + command_json + stop_lines；截图 /tmp/m5_training.png） |
| 红线 | 不启动训练（training_started=false） | ✅（平台只标记 authorized，不执行；冻结值不变） |

## M6 验收矩阵

| 项 | 验收标准 | 结果 |
|---|---|---|
| PG 原生/容器 | 真实通过 | ✅（brew postgresql@16 演练集群；单次迁移 16/16 表行数+哈希 match，0.17s；生产切换仍为独立授权点） |
| 单次迁移核对 | 不双写；逐表行数+哈希一致 | ✅（migrate_sqlite_to_pg.py：依赖顺序建表+单事务插入+canonical sha256 双侧核对；真实演练 16/16 match；纯函数离线断言 4 项 + PG 门控测试 5 passed） |
| 可恢复 Worker | lease 认领/崩溃恢复/取消/超时/重试/dead-letter/背压 | ✅（22 TDD：崩溃后 lease 过期 requeue、不重复完成（attempt 记账、终态单一）；dead_letter 前缀；背压单轮放行；100 job 吞吐 <1s） |
| CAS 校验/备份/恢复/水位 | fail-closed | ✅（verify_all 检出损坏/缺失；backup→restore 往返 + 损坏归档拒恢复；真实开发库演练 archive_sha256 ac3f39e0…；水位 0.753） |
| 安全加固 | CORS/CSRF/分享链接/审计 | ✅（CORS 白名单预检拒非白名单 Origin；JSON POST 无表单路径；分享 token scope/有效期/吊销 fail-closed 真实 E2E；job/share 动作 audit_event 留痕） |
| 性能测试 | 吞吐基线 | ✅（100 job <10s 软上限测试；实测 <1s） |
| 崩溃不重复完成/计量 | worker 崩溃不重复完成/计量 | ✅（TDD crash recovery + attempt 唯一记账 + result 单写；真实 E2E attempt 恰 1） |
| 用户可见 | 8400 真实 E2E | ✅（jobs submit/poll/cancel/409；shares create/check/revoke；Web /#/training 未回归） |

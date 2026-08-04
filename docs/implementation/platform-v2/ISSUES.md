# Platform V2 — ISSUES

> 格式：ID | 状态 | 严重度 | 描述 | 处置

| ID | 状态 | 严重度 | 描述 | 处置 |
|---|---|---|---|---|
| PV2-001 | CLOSED | 高 | 8300 Label Studio 曾未运行 | 2026-08-05 主机健康聚合确认 Label Studio healthy；保留历史事件 |
| PV2-002 | OPEN | 高 | 8301 ml-backend、8304 orchestrator 未运行 | 8400 如实显示 degraded；统一标注可用，但自动预标注 backend 和旧 orchestrator 不可用 |
| PV2-003 | OPEN / P0 | 高 | `src/eval/truebox_eval.py` 的 recall@FP 实为 recall@TopK（每图取 top-K proposal，非统一阈值真实 FP/photo 扫描） | M5 REOPENED；修复前不得用于晋级或启动 T2 |
| PV2-004 | OPEN | 中 | 旧 `/retrain` 的 auto_switch=true 不合规 | 新平台禁止该语义；M5 训练与发布分离审批 |
| PV2-005 | OPEN | 中 | `src/ls_platform/jobs.py` daemon thread 不可靠恢复（orphaned 无法识别） | M2 Job/Attempt 状态机 + M6 可靠 Worker 解决 |
| PV2-006 | OPEN | 低 | 8455 omlx 根路径 404（进程在，健康端点未知/需 API key） | W2 适配器按 unavailable/degraded 标记，探测路径待确认 |
| PV2-007 | CLOSED | 低 | 分支切换时工作树有未提交改动（README/program 索引切换 + 新手册文件） | 确认为用户为新手册做的入口切换，随 feat/usable-platform-foundation 保留并纳入 M0 提交 |
| PV2-008 | OPEN / P0 | 高 | 训练 dry-run 生成 `--dataset`、`--budget-minutes`，真实 `train_v1.py` 不接受 | 从真实 Snapshot 生成 `--data-yaml` 等合法参数并做 CLI parse 预检 |
| PV2-009 | OPEN / P0 | 高 | 唯一 DatasetSnapshot 是 2 train + 1 val 演示 manifest，却命名 `e2_product_pilot@v1` | 标记不可训练；由服务端 builder 生成真实、逐文件可验证 Snapshot |
| PV2-010 | OPEN / P0 | 高 | Snapshot API 接受自由 JSON 和自由文本人工结论，只检查 sha/store/session | 禁止客户端自证；补 photo_id/规范门店/模糊别名/session/SHA/近重复/冻结协议/标签审核/质量守卫 |
| PV2-011 | OPEN / P0 | 高 | MPS G0 仅以 `sys.platform == darwin` 判定 | 实测 torch MPS built/available、矩阵、模型前向、无 fallback、资源与电源 |
| PV2-012 | OPEN / P0 | 高 | API 角色依赖客户端 `X-Role`/`X-Actor`；Run 上传、执行和人工批准缺少真实身份边界 | 本机 session + CSRF；API/Agent token scope；服务端角色；所有写动作审计 |
| PV2-013 | OPEN / P0 | 高 | `start_training` 只把记录改为 authorized，不提交 Worker Job，接口与 UI 名称误导 | 拆分批准与启动；启动生成可恢复 job/attempt/PID/log，状态一致 |
| PV2-014 | OPEN | 高 | 当前 Graph 是固定节点列表和 `for` 循环，max_loops 仅为同节点 attempt 上限 | 作为 sequential v1 保留；实现 typed edges、条件路由、反馈 loop、收敛、每轮预算和回放 |
| PV2-015 | OPEN | 高 | 数据资产页错误显示 CAS 未启用；没有真实 Asset/CAS/lineage/quality 列表 | 接 Asset API 和统一资产台账，移除静态假状态 |
| PV2-016 | OPEN | 高 | 标注只完成 assisted/blind 机械闭环；250 个 truebox 任务全部 pending | 建任务派发、认领、单审/盲抽/双审/仲裁、final box 和不可变导出 |
| PV2-017 | OPEN | 高 | 全部样板照片尚无统一去重、质量、用途和冻结角色台账 | 建 `source_asset_inventory_v1`；所有来源有 disposition，原图不动 |
| PV2-018 | OPEN | 高 | 第三批旧质量 gate 22,664 张仅判 5 张 bad；qa_v3 只验证 120 张且无人工金标准 | qpol_v2 + 500～1,000 张分层人工金标准与证据链 |
| PV2-019 | OPEN | 中 | 训练页混合活动训练、历史缓存和生产模型；重复 dry-run 无幂等/分页 | 分区展示状态；无活动 job 显示 idle；写操作幂等，列表分页筛选 |
| PV2-020 | OPEN | 中 | Web 以 M4/M5/Graph Runs/raw JSON 为中心，缺统一待办和业务下一步 | 按新手册 §4 实现角色首页、任务中心和业务语言 |
| PV2-021 | OPEN | 中 | 识别只支持单文件；缺 URL、批量、API、Agent 的统一 RecognitionTask、计费档位和证据 | 四入口共用服务层与任务/证据/Usage 口径 |
| PV2-022 | OPEN | 中 | truebox 错误账本不互斥；晋级 FP 只计 background，忽略重复/定位等 FP | 定义互斥分类和 FP 守恒式；门禁使用 total FP/photo |
| PV2-023 | OPEN | 中 | 100 个轻量 job 测试不足以证明每日 10 万照片能力 | 用真实照片按 pipeline 阶段做 sustained/burst/p95/p99/失败恢复 benchmark |
| PV2-024 | OPEN | 低 | 根 README 仅有标题、STATUS/服务和 HEAD 曾漂移 | 根入口已在本轮文档修正；后续建立只读状态生成与一致性检查 |

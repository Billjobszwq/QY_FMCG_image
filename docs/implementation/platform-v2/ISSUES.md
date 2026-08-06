# Platform V2 — ISSUES

> 格式：ID | 状态 | 严重度 | 描述 | 处置

| ID | 状态 | 严重度 | 描述 | 处置 |
|---|---|---|---|---|
| PV2-001 | CLOSED | 高 | 8300 Label Studio 曾未运行 | 2026-08-05 主机健康聚合确认 Label Studio healthy；保留历史事件 |
| PV2-002 | OPEN | 高 | 8301 ml-backend、8304 orchestrator 未运行 | 8400 如实显示 degraded；统一标注可用，但自动预标注 backend 和旧 orchestrator 不可用 |
| PV2-003 | FIXED（待 G-EVAL 机器证据关闭） | 高 | `src/eval/truebox_eval.py` 的 recall@FP 实为 recall@TopK（每图取 top-K proposal，非统一阈值真实 FP/photo 扫描） | U1-001/002 已改为全数据集统一置信度阈值扫描 + 独立参考实现互验（0908127）；G-EVAL 门禁证据待真实数据集 |
| PV2-004 | OPEN | 中 | 旧 `/retrain` 的 auto_switch=true 不合规 | 新平台禁止该语义；M5 训练与发布分离审批 |
| PV2-005 | OPEN | 中 | `src/ls_platform/jobs.py` daemon thread 不可靠恢复（orphaned 无法识别） | M2 Job/Attempt 状态机 + M6 可靠 Worker 解决 |
| PV2-006 | OPEN | 低 | 8455 omlx 根路径 404（进程在，健康端点未知/需 API key） | W2 适配器按 unavailable/degraded 标记，探测路径待确认 |
| PV2-007 | CLOSED | 低 | 分支切换时工作树有未提交改动（README/program 索引切换 + 新手册文件） | 确认为用户为新手册做的入口切换，随 feat/usable-platform-foundation 保留并纳入 M0 提交 |
| PV2-008 | FIXED（待 T0 真实执行证据关闭） | 高 | 训练 dry-run 生成 `--dataset`、`--budget-minutes`，真实 `train_v1.py` 不接受 | U1-003 已改：dry-run 只生成 train_v1 真实参数并入库前 `--parse-check` 子进程预检（433f995） |
| PV2-009 | PARTIAL | 高 | 唯一 DatasetSnapshot 是 2 train + 1 val 演示 manifest，却命名 `e2_product_pilot@v1` | 已标 trainable=0 不可训练（c5fcca2）；builder 已就绪（50e39ff）；真实 Snapshot 待 U2/U3 真实照片接入 |
| PV2-010 | FIXED | 高 | Snapshot API 接受自由 JSON 和自由文本人工结论，只检查 sha/store/session | U1-005 服务端 builder：POST /snapshots → 410；逐文件存在/SHA/标签/data.yaml/五键守卫/近重复/协议/质量/审核校验（50e39ff） |
| PV2-011 | FIXED | 高 | MPS G0 仅以 `sys.platform == darwin` 判定 | U1-006 `mps_gate.run_mps_g0` 十项实测（7cd3c81）；T0 两跑 G0 ok=true 机器证据（d58d554，.eval/t0/t0_preflight_evidence_*.json） |
| PV2-012 | PARTIAL | 高 | API 角色依赖客户端 `X-Role`/`X-Actor`；Run 上传、执行和人工批准缺少真实身份边界 | U1-007 本机 session + CSRF + 服务端 role 已落地（4085023）；前端登录 UI 已上线（87f16d5）；API/Agent token scope 待 U2 |
| PV2-013 | FIXED | 高 | `start_training` 只把记录改为 authorized，不提交 Worker Job，接口与 UI 名称误导 | U1-008 approve_plan 与 enqueue_training_job 拆分；Worker training.run 真实子进程留 PID/日志（5c13177）；UI 分区 + idle 显式（87f16d5） |
| PV2-014 | OPEN | 高 | 当前 Graph 是固定节点列表和 `for` 循环，max_loops 仅为同节点 attempt 上限 | 作为 sequential v1 保留；实现 typed edges、条件路由、反馈 loop、收敛、每轮预算和回放 |
| PV2-015 | OPEN | 高 | 数据资产页错误显示 CAS 未启用；没有真实 Asset/CAS/lineage/quality 列表 | 接 Asset API 和统一资产台账，移除静态假状态 |
| PV2-016 | OPEN | 高 | 标注只完成 assisted/blind 机械闭环；250 个 truebox 任务全部 pending | 建任务派发、认领、单审/盲抽/双审/仲裁、final box 和不可变导出 |
| PV2-017 | OPEN | 高 | 全部样板照片尚无统一去重、质量、用途和冻结角色台账 | 建 `source_asset_inventory_v1`；所有来源有 disposition，原图不动 |
| PV2-018 | OPEN | 高 | 第三批旧质量 gate 22,664 张仅判 5 张 bad；qa_v3 只验证 120 张且无人工金标准 | qpol_v2 + 500～1,000 张分层人工金标准与证据链 |
| PV2-019 | PARTIAL | 中 | 训练页混合活动训练、历史缓存和生产模型；重复 dry-run 无幂等/分页 | 分区展示 + 无活动 job 显 idle 已上线（87f16d5）；dry-run 幂等与列表分页筛选待 U2 |
| PV2-020 | OPEN | 中 | Web 以 M4/M5/Graph Runs/raw JSON 为中心，缺统一待办和业务下一步 | 按新手册 §4 实现角色首页、任务中心和业务语言 |
| PV2-021 | OPEN | 中 | 识别只支持单文件；缺 URL、批量、API、Agent 的统一 RecognitionTask、计费档位和证据 | 四入口共用服务层与任务/证据/Usage 口径 |
| PV2-022 | FIXED（待 G-EVAL 机器证据关闭） | 中 | truebox 错误账本不互斥；晋级 FP 只计 background，忽略重复/定位等 FP | U1-002 互斥分类 + FP 守恒式 + 门禁用 total FP/photo（0908127） |
| PV2-023 | OPEN | 中 | 100 个轻量 job 测试不足以证明每日 10 万照片能力 | 用真实照片按 pipeline 阶段做 sustained/burst/p95/p99/失败恢复 benchmark |
| PV2-024 | OPEN | 低 | 根 README 仅有标题，STATUS/服务和 HEAD 曾漂移 | 根入口已在本轮文档修正；后续建立只读状态生成与一致性检查 |
| PV2-025 | OPEN | 高 | T0 实测系统 swap used=10867MB 超 8192MB 停止线（含其他进程），训练启动前必须处置（重启释放/关无关进程/降 batch）；另 mps_gate swap 解析曾被 macOS 15 格式掩盖（已修，d58d554） | 证据如实 exceeds_stop_line=true；T1 授权前需复测 swap 降至停止线下 |
| VLM-ISSUE-001 | OPEN | 高 | STATUS.md 写 training_started=false（冻结）/训练 NO-GO，但 sku_v7_sam 实际自 2026-08-05 起真实运行（PID 90423，用户授权、平台治理系统外启动），治理冻结值与实际训练状态冲突 | 如实对账：STATUS 标注为 RUNNING_EXPERIMENTAL（平台外、非平台发布判定）；冻结值 training_started=false 语义保持不变（平台治理未启动过训练）；训练结束后补最终评估文档 |
| VLM-ISSUE-002 | OPEN | 高 | sku_v7_sam 启动命令含 --lr0 0.0005，但 ultralytics optimizer=auto（默认）时 MuSGD 实际 lr=0.01，lr0 参数被忽略 | 如实登记不修改运行中训练；训练结束后评估报告中必须披露；下一轮训练显式指定 optimizer |
| VLM-ISSUE-003 | OPEN | 高 | 质量筛选中 934/944 张 reject 主要来自 tilt 启发式（水平线不足 fail-closed 返回 1.0），缺少人工金标准验证 | VLM-008：缺水平线改判 manual_review（reason code tilt_unobservable）；单一弱启发式不得直接 reject；旧 934 张作为历史证据保留进人工复核队列，不改写旧 JSON |
| VLM-ISSUE-004 | OPEN | 中 | SAM 精修接受率 96.5% 只代表几何通过（紧框合法/未逃逸），不代表框内 SKU 类别正确（类别沿用原框坐标定位） | 如实登记；后续需 truebox/SKU 人工抽检才能判定标签正确性 |
| VLM-ISSUE-005 | OPEN | 中 | Qwen3-VL/MLX 尚未安装（无 mlx、mlx-vlm、transformers 依赖，无权重下载） | 本轮只实现代码+mock 测试；真实安装/下载需用户显式授权且在无训练冲突时执行 |
| VLM-ISSUE-006 | OPEN | 高 | sku_v7_sam 正在使用 MPS 训练（epoch 31/120，约 21h），所有真实 MLX/Qwen 重任务（下载/前向/LoRA/shadow）被资源门禁阻断 BLOCKED_BY_ACTIVE_TRAINING | 本轮只交付门禁代码与 mock 测试；训练自然结束且用户再次授权后才能启动 Qwen 真实阶段 |

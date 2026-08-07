# 验收门、停止线与最终汇报格式

## G0 基线可信

- fresh HEAD/branch/status/commit chain；
- 默认 hermetic suite 全绿，host MPS 独立全绿；
- 交付报告与现场差异已更正文档；
- DB integrity、服务、bundle、进程、磁盘、内存、swap 有证据；
- 未删除/覆盖/清理任何历史文件。

## G1 Label Studio 与身份

- 208 Registry = 208 taxonomy，双向差集 0；
- assisted 可见 proposal、可改、刷新保持；no_proposal 可手工画框；
- blind predictions/meta=0；
- SKU/name/package/unknown 均使用 canonical ID；
- prediction 永不自动变 gold。

## G2 三批资产与严格过滤

- 2,947/6,510/22,664 原始照片计数对账；
- exact unique=29,176，canonical points=745,695；不一致即停止并解释；
- 476 个坐标差异有 ledger；
- 全量 near-dup 分组完成并用于 split；
- 严格质量维度、四级结论、人工校准、误拒绝率和证据链完整；
- old batch3 5 张 reject 不被当作新筛选结论。

## G3 SAM 数据质量

- prompt/negative point/ROI/candidate 选择可追溯；
- mask/tight box/crops 与原资产一一映射；
- 所有拒绝理由可审计；
- ≥2,000 region 分层 mask audit，或如实停在等待人工；
- pseudo mask 与 human gold 字段/权限/用途结构隔离。

## G4 四 Snapshot

- D1–D4 独立 schema、manifest/hash/builder/source/quality/split/exclusion；
- 五键泄漏 0；
- 208 已知 SKU 与 40,591 unknown 点处置清楚；
- train/val/eval 与 near-dup/package group 不跨分割；
- CandidateSet builder 签名无 GT；
- 输出目录不覆盖。

## G5 Graph+Loop 与 API

- Graph 状态持久化，服务重启可恢复；
- API 能计划、批准、启动、安全停止、恢复、看事件/制品/评估；
- session/CSRF/RBAC/idempotency/参数白名单有效；
- Graph/API/Worker/DB 只有一个写事实源；
- Agent 不能执行任意 shell/SQL/文件路径。

## G6 UI 与 Profile

- 数据准备、SAM、数据集、四 Lane、Run Detail、Graph Run 都可图形化操作；
- 每个按钮连接真实 API，无空壳；
- Recognition 可选择版本化 profile；
- 单文件/批量/URL/API/Agent 选择与结果审计同口径；
- 旧生产与 nextgen candidate 视觉隔离；不可用 profile 明示 blocker；
- 浏览器刷新/重复点击/多标签页不重复建任务。

## G7 Apple 资源与并发

- Worker launch 前在真实环境重跑 G0；
- 单任务与并发 benchmark 均有 measured 证据；
- 只有 throughput ≥25% 且所有安全线通过才允许并发 2；
- 不默认并发 3；
- Qwen 绝对独占；
- 训练期间 8091/8400/8300 健康和 p95 受保护。

## G8 四模型真实训练

每个模型都必须有：

- approved TrainingPlan；
- dataset/base/code/config/env hash；
- 真实 PID、heartbeat、resource lease；
- loss/metric curve、best/last checkpoint、SHA；
- stop-line 判定与最终 exit；
- frozen evaluation + error ledger；
- candidate registry；
- production switch=false。

模型没跑不能用 adapter 单测冒充完成；未通过 pilot 可诚实停止，但必须给出失败结果和下一实验假设。

## G9 业务评估

- 旧最好模型与四个新 candidate 同口径比较；
- 每项指标有分母、冻结集 hash、coverage；
- E2E profile 报准确率/召回/复核率/p95/吞吐/内存/成本；
- human truth 不足时写 `not_evaluable` 或 interim，不伪造 95%；
- shadow/publish 仍待独立批准。

## 立即停止线

- 原图、历史模型、DB 事实或旧报告被覆盖/删除；
- 旧业务权重进入 nextgen parent/resume/EMA/optimizer；
- blind 出现 prediction/model meta；
- pseudo/model proposal 写成 human gold；
- 三批计数或坐标身份无法对账；
- split 五键泄漏；
- MPS fallback、OOM、NaN/Inf、memory pressure red、thermal serious/critical；
- swap ≥8GB 或单次 benchmark 增量 >2GB；
- 生产服务错误，p95 >基线 1.2×；
- Qwen 与其他 heavy 任务并发；
- production bundle 被自动切换；
- SQLite integrity 失败。

## 最终汇报格式

Agent 必须一次性按以下编号交付；没有结果写“未完成/阻断”，不得省略：

1. Git HEAD、分支、工作树、commit 链；
2. 必读文件清单与基线差异；
3. 删除/覆盖/生产切换声明；
4. fresh tests：hermetic/host/TS/Vite/DB/browser；
5. 服务、bundle、进程与 Apple 资源；
6. Label Studio 208 标签三方对账；
7. assisted/no_proposal/blind 统计与浏览器证据；
8. 三批原始计数、SHA 去重和 canonical 规则；
9. 476 坐标差异与 near-dup 结果；
10. 严格质量各维度、四级分布、人工校准和误拒绝率；
11. SKU Registry/alias/unknown 40,591 点处置；
12. SAM 版本、prompt 策略、成功/拒绝/人工数；
13. mask audit 数量、IoU/precision 和分桶；
14. D1 detector snapshot/hash/split/exclusion；
15. D2 segmenter snapshot/hash/split/exclusion；
16. D3 classifier snapshot/hash/split/exclusion；
17. D4 VLM snapshot/hash/split/CandidateSet/format smoke；
18. Graph 持久化、恢复、幂等与 Hook 验证；
19. API 清单、鉴权与契约测试；
20. Web 七个工作区与浏览器 QA；
21. Recognition profiles 和五入口同口径证据；
22. 单任务/并发资源 benchmark 与最终排程决定；
23. M1 detector 计划、耗时、曲线、指标、artifact SHA、决定；
24. M2 YOLO-seg 计划、耗时、曲线、指标、artifact SHA、决定；
25. M3 classifier 计划、耗时、曲线、指标、artifact SHA、决定；
26. M4 Qwen QLoRA 计划、耗时、曲线、指标、artifact SHA、决定；
27. 四模型同口径 baseline 对比；
28. E2E profiles 的准确/覆盖/复核/p95/吞吐/内存/成本；
29. safe-stop/orphan/服务重启/磁盘/MPS/Qwen OOM 演练；
30. 未关闭问题与证据路径；
31. 当前 Cycle/各 Lane 状态；
32. `full training started`、`production switch`、`publish` 明确布尔值；
33. 最终判定：`NEXTGEN_TRAINING_CYCLE_V2_COMPLETE`、`...AWAITING_HUMAN_EVALUATION` 或 `BLOCKED/FAILED`；
34. 唯一下一步，不再列重复建设任务。


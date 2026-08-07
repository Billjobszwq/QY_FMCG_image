# 当前状态复核与开训判断

## 1. 结论先行

本次交付已经完成了训练控制的契约、部分数据库表、Worker 原语、四 Lane 只读投影和 Web 卡片，但报告中的“机器侧全部收口”结论过度。当前状态应改判为：

```text
CONTROL_CONTRACTS_PRESENT_BUT_EXECUTION_CHAIN_INCOMPLETE
```

因此不能直接从现有页面启动四模型训练。可以在同一实施任务中先补齐控制链、重建数据，再按本手册的有界授权自动进入实验训练；不需要每完成一个小步骤就重新询问，但任何生产切换仍需单独授权。

## 2. Git、测试和工作树复核

| 项目 | 现场事实 |
|---|---|
| Branch | `feat/unified-workbench-training-readiness` |
| HEAD | `ce6f614468f88146d85d23a3ee7bcb5391acfb35` |
| 报告声称 | 默认 `1010 passed, 1 skipped, 5 deselected` |
| 2026-08-08 fresh run | **`1002 passed, 8 failed, 1 skipped, 5 deselected`** |
| 失败性质 | 旧测试仍把 macOS 等同于 MPS 可用；受限进程 MPS/sysctl 不可见，导致训练治理与 SAM runtime 测试失败 |
| 工作树差异 | 除四个受保护目录外，还有 3 个 backfill JSON 与 1 张 Web QA 截图未跟踪；报告的“仅 4 个目录”不准确 |

新任务必须首先使默认 hermetic suite 真正不依赖宿主 MPS，并把真实 Apple/MPS 检查放入独立 host suite。禁止通过删测试、放宽断言或伪造 `mps_available=true` 获得全绿。

## 3. Label Studio 标签与提案核验

本次通过 `configs/label-studio/label_config.xml`、`data/sku_registry.json` 和 `.label-studio/label_studio.sqlite3` 三方核对：

| 检查 | 结果 |
|---|---|
| Registry SKU | 208 |
| Label config taxonomy choices | 208，唯一 208 |
| Registry 缺失于 taxonomy | 0 |
| Taxonomy 越界于 Registry | 0 |
| Project 19 / 20 config hash | 均为 `e2092027f928fb64`，配置一致 |
| Project 19 assisted | 200 tasks；187 有 prediction/框；186 有可见 SKU taxonomy；13 标记 `no_proposal` |
| Project 20 blind | 50 tasks；prediction=0；模型 meta=0，隔离正确 |
| 非法 taxonomy 值 | 0 |

结论：**Label Studio 中人工可选择的 208 个 SKU 标签完整存在。**

需要正确理解“标签存在”和“每个任务都有自动建议”的区别：

- 13 个 assisted 任务因模型零检出而没有自动框/自动 SKU，保留任务并标 `no_proposal` 是正确的；
- 另有 1 个任务有框和状态，但因低置信进入 `needs_manual_sku`，没有自动 SKU 建议；人工仍可从 208 个标签中选择；
- blind 项目必须永远没有 prediction，不应“修复”为自动建议。

训练前仍要做一次浏览器级回归：随机 SKU 搜索、区域选择、修改、刷新保存、no-proposal 手工画框、blind 零泄漏。

## 4. 三批照片与坐标的真实规模

| 来源 | 原始照片 | 坐标点 |
|---|---:|---:|
| 第一批 | 2,947 | 84,459 |
| 第二批 | 6,510 | 174,249 |
| 第三批 | 22,664 | 571,404 |

精确 SHA 关系：

- 第一/第二批重叠 2,945 张；第一批独有 2 张；
- 第一/第三、第二/第三精确重叠均为 0；
- 三批原始照片精确去重后为 **29,176 张**；
- 第一/第二批重叠照片中，2,469 张坐标列表完全相同，476 张存在差异，不能静默覆盖；
- 按“第二批优先、第一批补独有、第三批独立”得到 **745,695 个 canonical 坐标点**。

旧 `.batch3_clean` 只拒绝 5 张反光图（22,664 -> 22,659），没有覆盖严重斜拍、翻拍、摩尔纹、大头照误导、主体过小/遮挡等完整风险，不能作为严格过滤结果继续使用。本轮必须从三批原始输入重新执行，旧结果只作历史对照。

## 5. SKU 身份覆盖风险

第一/二批 174,291 个 canonical 点均可映射 Registry。第三批存在 5 个未映射名称，共 40,591 点：

| 原始名称 | 点数 | 处置 |
|---|---:|---|
| `other` | 22,650 | 显式 unknown/难负样本，不强映射 |
| `百事other` | 9,720 | 品牌层 unknown/难负样本，不强映射 |
| `可乐other` | 8,216 | 品类层 unknown/难负样本，不强映射 |
| `24-元气森林-元气自在水-500ml-PET瓶-陈皮山楂水500ml` | 4 | alias/new SKU 人工裁决 |
| `怡泉+C500ml柠檬味` | 1 | alias/new SKU 人工裁决 |

不得为了提高覆盖率把这些名称猜成现有 208 类。已知 canonical SKU 点为 705,104；unknown 点可进入商品几何检测、unknown 分类和 VLM 拒答训练，但不能进入错误的闭集类别。

## 6. 当前控制面真实缺口

### 6.1 NextGen Web 是只读状态卡，不是训练控制台

`TrainingControl.tsx` 当前只请求 lanes/overview/legacy-models，没有创建计划、批准、启动、停止、恢复、日志、制品、评估或并发计划的操作。可操作按钮仍位于折叠的 Legacy 单 YOLO 区。

### 6.2 NextGen API 没有真实执行写链

现有 V2 API 只有：

- lanes/readiness/overview/legacy-models/runs/events 查询；
- dataset build 一个写端点。

它缺少 Plan、approval、launch、safe-stop、resume、artifact、evaluation、candidate 和 concurrency benchmark 的正式端点。dataset build 端点还固定传 `rows=[]`，没有从真实事实源读取三批资产、坐标、质量和标签。

### 6.3 Graph 与数据库/Worker 没有形成唯一运行状态

`TrainingControlGraph` 当前将 run/audit 保存在进程内字典；API 没有驱动它，Worker 也没有由 Graph 状态和持久化 outbox 编排。服务重启后无法把内存 Graph 当作唯一事实源。

### 6.4 Adapter 主要是契约壳

Adapter 可以校验少量参数、构造字典和透传结构化事件，但没有完整连接真实训练 launcher、checkpoint、heartbeat、曲线、评估和 Candidate Registry。当前 evaluation 的默认阈值仅 0.3/0.5，不能作为本轮业务晋级线。

### 6.5 识别页没有模型/Profile 选择

`Recognition.tsx` 和 recognition tasks API 仍使用固定 adapter，没有 `recognition_profile_id`；页面还显示过期的 `prod_20260804_v4_r2` 文案。单文件、批量、URL、API、Agent 无法选择并记录同一个模型链配置。

## 7. 本轮允许与禁止

允许：

- 修复上述控制链；
- 重建三批资产、质量、SAM 派生和四类数据集；
- 在所有数据/硬件/资源门通过后，依本任务书启动四条**实验候选**训练；
- 在安全 benchmark 证明有收益时并行两个非 Qwen 重任务；
- Qwen 独占运行；
- 训练完成后做冻结集评估和 shadow 准备。

禁止：

- 删除或覆盖原图、旧数据、旧模型、历史报告和 SQLite 记录；
- 继承任何旧业务 checkpoint 作为 nextgen parent/resume/EMA/optimizer；
- 把 SAM 伪 mask 当人工 gold；
- 用 train/val 自评代替独立冻结集；
- 自动切换生产 bundle；
- 因为测试框架存在就声称真实训练已可控。


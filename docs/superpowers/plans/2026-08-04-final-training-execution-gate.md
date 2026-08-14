# Final Training Execution Gate Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不浪费 Apple M3 Max 资源、不污染冻结评估集、不覆盖既有训练制品的前提下，给出本项目最终训练准入结论、阻断项、Apple Silicon 执行规范、实验顺序和停止条件。

**Architecture:** 保持“单类商品 proposal detector + SKU classifier + unknown/review gate + immutable bundle”的目标级联架构。训练与评估按数据协议、真实框诊断、detector、classifier、完整级联、发布六层解耦；每层必须先通过独立门禁，禁止用下游 accuracy 掩盖上游漏检。

**Tech Stack:** Apple M3 Max、arm64 Python、PyTorch MPS、Ultralytics YOLO、torchvision、内容哈希数据版本、one-to-one IoU 评估、pytest、immutable model bundle。

---

## 0. 审查边界与最终结论

本次只检查代码、测试、数据协议、现有制品、运行服务、机器资源和训练历史，并编写 Markdown 手册。没有修改任何代码、配置、数据、数据库或模型，也没有启动训练、重启服务或发布模型。

### 0.1 三个结论必须分开理解

| 结论对象 | 状态 | 最终判断 |
|---|---|---|
| Apple Silicon / MPS 兼容性 | **GO** | M3 Max、arm64 Python、PyTorch MPS 均已实测可用；不需要换 CUDA 机器才能开始实验 |
| 当前线上基线与只读评估 | **GO** | 生产 bundle 可校验、识别服务健康、测试通过，可继续作为对照组 |
| 立即执行正式全量训练 | **NO-GO** | 数据构建、冻结集隔离、真实框评估、E0 指标口径和训练输出覆盖风险仍未闭环 |
| 完成本文 G0～G6 后的小规模 pilot | **CONDITIONAL GO** | 先做有限 pilot，再根据严格指标决定是否投入全量训练 |

因此，**Apple 处理器不是当前阻断项**。真正阻断正式训练的是数据与评估可信度。现在直接续跑 44 epoch 或从 `sku_v6_ep6.pt` 恢复，会同时浪费 M3 Max 算力和破坏实验结论。

### 0.2 当前明确禁止的动作

在本文阻断项关闭前，不执行：

1. 不从 `.models/sku_v6_ep6.pt`、`sku_v6_p1` 或任何旧 v6 checkpoint 恢复训练。
2. 不直接运行默认 `python -m src.training.build_sku_v6_dataset`。
3. 不对现有 `.datasets/sku_v6`、`crop_dataset` 或 `crop_dataset_yolo` 继续正式训练。
4. 不直接运行 classifier 默认入口；它仍固定读取旧 `crop_dataset`。
5. 不把 E0 报告中的 `89.0%` 当成端到端 accepted precision。
6. 不因为机器有 128 GB 统一内存就盲目放大 batch；先测吞吐、内存高水位和收敛。

---

## 1. 本次复核证据快照

### 1.1 代码、Git 与测试

| 检查项 | 结果 |
|---|---|
| Git 工作树 | 审查开始时 clean |
| 当前分支 / HEAD | `main` / `3f13fa6` |
| `origin/main` | 与本地 HEAD 一致 |
| 当前标签 | `app-v0.1.0`、`app-v0.2.0` |
| 远端 | 已配置；远端仓库隐私属性本次未独立验证 |
| 自动化测试 | `46 passed in 2.04s` |
| Python 语法检查 | 88 个 Python 文件通过 AST 解析 |
| 114 个 tracked 非 Markdown 文件组合哈希 | `509c98f8c60157eba2f9bef77480412dd410a2e253a7553ddd69255838bae2dc` |

组合哈希按“逐文件 SHA256 输出含路径 → 路径排序 → 再做 SHA256”计算，便于证明本轮文档编辑前后非 Markdown 资产未变化。测试数量的提升是真实进展，但 46 项测试仍不能证明当前 builder 可以端到端生成安全的新数据集，也不能替代冻结集门店/会话隔离和严格 IoU 评估。

### 1.2 当前系统运行状态

| 项目 | 结果 |
|---|---|
| 8091 recognize | LISTEN，`/v2/health` HTTP 200 |
| 8092 monitor | LISTEN，`/api/live` HTTP 200 |
| 8300 / 8301 / 8304 | DOWN；本次未做 Label Studio、ML backend、orchestrator 在线联调 |
| 当前 bundle | `prod_20260804_v4_r2`，16 个文件校验通过 |
| detector | sku_v4，SHA 与 bundle 一致 |
| classifier | ResNet18，208 类，epoch 10，记录 val_acc 83.67% |
| 当前训练进程 | 无 |
| recognize RSS | 约 910 MiB |
| monitor RSS | 约 248 MiB |
| monitor 连续稳定性 | 本次只观察约 34 分钟，尚不能替代 2 小时长稳验证 |

### 1.3 机器资源

| 项目 | 实测 |
|---|---|
| 机器 | MacBook Pro `Mac15,9` |
| SoC | Apple M3 Max |
| CPU | 16 核，12 性能核 + 4 能效核 |
| GPU | 40 核 |
| 统一内存 | 128 GB |
| 系统架构 | arm64 |
| 磁盘 | 约 7.3 TiB，总可用约 5.5 TiB |
| 电源 | 审查时接入电源，电池 100% |

现有主要资产约为：`.models` 2.7 GB、`.datasets` 76 MB、`training_data` 3 GB、`.batch3_clean` 10 GB、`crop_dataset` 1.4 GB、`crop_dataset_yolo` 537 MB、`.eval` 355 MB。当前磁盘不是训练瓶颈。

---

## 2. Apple Silicon 最终确认

### 2.1 已通过的原生性检查

| 检查 | 结果 | 判断 |
|---|---|---|
| Python 二进制 | `python3` 为 Mach-O arm64 | 原生运行，不是 Rosetta x86_64 |
| Python / torch | Python 3.13.2，torch 2.13.0 | 当前环境可加载 |
| torchvision / Ultralytics | torchvision 0.28.0，Ultralytics 8.4.113 | 与现有训练日志一致 |
| `torch.backends.mps.is_built()` | `True` | PyTorch 包含 MPS 支持 |
| `torch.backends.mps.is_available()` | 在真实终端环境为 `True` | 当前 macOS 和 GPU 可用 |
| MPS 张量 | 1024×1024 矩阵乘法成功 | 不是只检测到设备而无法计算 |
| 当前级联 MPS 推理 | dev 照片成功，2 个 prediction，约 0.543 秒 | 当前模型可在 MPS 上实际执行 |
| 历史 YOLO 训练日志 | 明确记录 `MPS (Apple M3 Max)` | 过去训练确实使用 Apple GPU |

结论：**当前训练栈符合 Apple 处理器架构，可以使用 MPS 和统一内存，不应切换到 CPU 全量训练。**

PyTorch 官方推荐用 `torch.backends.mps.is_available()` 检查，并将张量/模型移动到 `mps` 设备；Ultralytics 官方训练接口也明确支持 `device="mps"`。参考：[PyTorch MPS 文档](https://docs.pytorch.org/docs/stable/notes/mps.html)、[Ultralytics 训练文档](https://docs.ultralytics.com/modes/train/)。

### 2.2 Codex 沙箱假阴性的说明

在 Codex 受限沙箱内，`is_built=True` 但 `is_available=False`，张量创建返回通用 macOS 版本错误；在经批准的真实终端环境中，同一 Python 随即通过 MPS 张量和级联推理。此差异属于执行环境限制，不能据此判定 Mac 不支持 MPS。

训练前的准入检查必须在实际启动训练的 Terminal 会话执行，不能把 Codex 沙箱结果作为硬件事实。PyTorch 官方 issue 中也有相同类型的 `is_built=True / is_available=False` 诊断案例，可用于理解环境差异，但本项目以本机真实计算成功为最终证据：[PyTorch issue #177819](https://github.com/pytorch/pytorch/issues/177819)。

### 2.3 每次训练前必须执行的 G0 命令

以下命令只做只读/计算检查，不开始训练：

```bash
file python3

python3 -c 'import platform,torch; print("arch",platform.machine()); print("torch",torch.__version__); print("mps_built",torch.backends.mps.is_built()); print("mps_available",torch.backends.mps.is_available()); assert platform.machine()=="arm64"; assert torch.backends.mps.is_available(); x=torch.randn(1024,1024,device="mps"); y=x@x; print("mps_tensor_ok",y.shape,y.device)'

pmset -g batt
pmset -g custom
```

通过标准：

- `arch arm64`
- `mps_built True`
- `mps_available True`
- `mps_tensor_ok torch.Size([1024, 1024]) mps:0`
- 已接电源
- 系统设置中人工确认当前为“高电量模式/High Power Mode”，而不是低电量模式

Apple 官方说明，高电量模式可允许风扇以更高速度运行并提高高强度工作负载的持续性能，M3 Max 支持该模式。命令行电源字段在本机显示存在歧义，因此训练前以 macOS 系统设置中的可视状态为准：[Apple 高电量模式说明](https://support.apple.com/en-mide/101613)。

任何一项不通过都停止训练，禁止静默切换到 CPU。

### 2.4 Apple MPS 资源策略

1. detector 所有训练命令显式使用 `--device mps`，不得省略。
2. classifier 当前代码会在 MPS 不可用时自动落到 CPU；因此必须先跑 G0 断言，再启动 classifier。
3. 初始 `imgsz=960`、`batch=4`。历史 `imgsz=1024 / batch=4` 已使用约 13～16 GB 统一内存，说明 batch 4 稳妥，但不能据此直接放大到 16 或 32。
4. 先运行 200～500 step 吞吐探针。只有 loss 正常、内存不持续增长、系统无明显 swap 压力时，才单变量试 `batch=8`。
5. `workers=4` 作为基线。数据加载明确成为瓶颈后，才对比 6 或 8；不要默认把所有 16 个 CPU 核耗满。
6. 不主动设置 `PYTORCH_ENABLE_MPS_FALLBACK=1`。fallback 会把不支持的算子移到 CPU，掩盖性能问题；只有定位到具体算子且记录代价后才可作为临时实验。
7. classifier 的 `pin_memory=True` 在历史日志中已提示 MPS 不支持；这是无效开销和噪声，后续实现应按设备关闭。
8. 长训练使用 `caffeinate` 保持会话唤醒，但它不能替代接电、高电量模式和温度监控。
9. 训练期间禁止并行运行另一个大模型训练；8091/8092 可保留做轻量观察，但开始前记录其 RSS，异常增长时停训排查。

### 2.5 MPS 的可复现性边界

历史日志已经出现 `index_put_with_accumulate_mps` 没有 deterministic 实现的警告。即使 Ultralytics 传入 `deterministic=True`，MPS 结果也不能承诺逐 bit 完全一致。

因此正式比较使用三个固定 seed：`42`、`20260804`、`3407`，报告均值、标准差和最差值。MPS 上的“可复现”定义为指标落在可接受统计区间，而不是 checkpoint 字节完全相同。

---

## 3. 阻止立即全量训练的关键问题

### G1：旧 v6 lineage 污染新协议集

现有 `.datasets/sku_v6` 训练门店与冻结集存在大量重叠：calibration 51、dev 102、diagnostic 68、gold 168 个门店；旧 val 也分别重叠 8、10、11、17 个门店。

这意味着任何从 `sku_v6_ep6.pt` 或 `sku_v6_p1` 继续的模型，都不能再把当前四个协议集称为未见门店评估。允许的初始化只有：

- `best/sku_v4_best.pt`，但必须先修复 dev_v1 中与 batch2 的两个门店别名；或
- 官方预训练 `yolo26m.pt`，从全新 lineage 开始。

旧 v6 权重保留作历史对照，不删除，但退出新一轮正式 lineage。

### G2：当前 builder 默认配置会 fail，而且泄漏检查不完整

按当前默认 seed=42、batch3 budget=4000 做只读模拟，拟选数据与四个冻结集直接重叠：

| 冻结集 | photo/SHA 命中 | store 命中 |
|---|---:|---:|
| calibration_v1 | 16 | 71 |
| dev_v1 | 42 | 147 |
| diagnostic_v1 | 21 | 94 |
| gold_v2 | 56 | 226 |

当前 `_protocol_no_leak()` 只检查 photo ID 和 SHA，不检查门店、规范化别名或采集会话。默认构建会在 photo/SHA 检查处抛错；即使手工去除命中照片，门店泄漏仍会被放过。

修复验收必须同时满足：photo ID=0、SHA=0、规范化 store=0、fuzzy alias=0、session=0。

### G3：现有数据制品过期且可能混入残留文件

- `.datasets/sku_v6` 是协议冻结前旧制品；train/val 门店重叠 149 个。
- `crop_dataset_yolo` summary 比磁盘多 1,561 个文件。
- classifier 默认读取 `crop_dataset`，不是计划中的 predicted/jitter/unknown 数据。
- 当前 builder 写入固定 `.datasets/sku_v6`，目录 `exist_ok=True`，没有 staging + 原子发布，旧文件可能残留。

新训练数据必须生成到唯一版本目录，完整校验后才切换指针；禁止在旧目录上增量覆盖。

### G4：当前冻结集并非完整严格评估协议

四个协议集之间 photo ID、SHA 和精确门店交集为 0；所有 blob 存在且 SHA 匹配，这是有效进展。但仍有以下缺口：

1. dev_v1 有两个 Unicode/中英文括号规范化后的 batch2 门店别名重叠。
2. `_norm_store` 当前只做 trim/casefold，没有完成标点全半角和模糊别名归一化。
3. 协议 JSON 文件权限为 644，Git 可追溯但不是真正文件系统只读。
4. `gold_v2` 覆盖 207/208 类，缺少 class 189；19 个类少于 10 个实例。
5. 协议 JSON 只保存照片清单与统计，没有完整真实矩形框。

dev_v1 必须发布追加版 `dev_v2`，移除并替换两个别名门店。gold_v2 可以继续用于从 v4/COCO 初始化且严格排除其门店的新 lineage，但不得用于评价任何继承旧 v6 的模型。

### G5：E0 指标口径高估，且不是严格 IoU

E0 的原始计数为：

- accepted correct：4,126
- matched accepted wrong：439
- unknown false accept：70
- unmatched accepted FP：2,190

报告中的 89.0% 实际是 `4126 / (4126 + 439 + 70)`，只计算“已与 GT 匹配的 accepted proposal”。若把 accepted FP 纳入业务分母，端到端 accepted precision 是：

```text
4126 / (4126 + 439 + 70 + 2190) = 60.45%
```

此外，E0 使用 point-in-box，不是真实 one-to-one IoU；detector conf=0.18 也未写入报告阈值区。故当前基线只能用于定位瓶颈，不能用于发布判断。

### G6：训练输出仍可能覆盖已有实验

`train_v1.py` 先对固定 run 目录 `mkdir(exist_ok=True)`，随后给 Ultralytics 传 `exist_ok=True`。Ultralytics 官方文档说明 `exist_ok=True` 允许覆盖已有 experiment。正式训练必须改为已存在即失败，并在训练前冻结 run manifest。

classifier 虽有独立 experiment 目录，但仍会先写全局 `.models/classifier/classes.json`；训练入口也不能显式指定数据目录。这两点关闭前不开始 classifier 正式训练。

---

## 4. 可用数据与模型方向判断

### 4.1 训练数据不是主要稀缺资源

在 batch3 中排除当前四个冻结集的 photo ID、SHA 和精确门店后，仍有：

| 项目 | 数量 |
|---|---:|
| 候选照片 | 19,205 |
| 候选门店 | 6,933 |
| 注册 SKU 实例 | 448,590 |
| 未注册实例 | 34,367 |
| 注册类覆盖 | 208/208 |
| 少于 10 个实例的类 | 1 类 |
| 少于 30 个实例的类 | 6 类 |

这说明下一步不应继续无差别收集更多同分布照片，而应先修复切分、真实框和 hard-negative 质量。

### 4.2 detector 优先级高于 classifier

E0 在 dev_v1 的检测覆盖仅 25.49%，端到端 accepted-correct recall 20.31%，FP/image 3.174。即使 classifier 立刻完美，漏检仍无法恢复。

下一主线应优先验证 **class-agnostic product detector**：把注册商品和未注册商品都标成单类 `product`，SKU 细分与 unknown 拒识交给 classifier。当前 208 类 detector 在 proposal 阶段承担了不必要的长尾分类压力。

### 4.3 classifier 不是立即扩模型规模

分类器下一步先回答三个问题：

1. true-box oracle 是否已达到目标；
2. predicted-box 相对 true-box 掉了多少；
3. unknown / hard negative 的 false accept 是否可控。

只有 true-box oracle 仍明显不足，才比较 EfficientNet-B0、MobileNetV3 或更强 backbone。否则应优先修裁剪分布、增强和校准，而不是扩大模型。

---

## 5. 最终训练顺序

### Phase A：关闭数据协议门禁，不训练（✅ 已全部完成，2026-08-04，commit abe2630）

- [x] 生成 `dev_v2`：以 Unicode NFKC、括号/标点统一、casefold、空白压缩和别名表做 store 规范化；替换两个与 batch2 重叠的门店。（`.data_protocol/dev_v2.json`，801 张）
- [x] builder 在抽样前排除 active protocol 的 photo ID、SHA、规范门店、模糊别名和 session。（五键守卫，exclusion={photo_id:2907, store_alias:515}）
- [x] 新数据集写入唯一 staging 目录；成功后原子发布，不复用 `.datasets/sku_v6`。（`.datasets/e2_product_pilot_v1`）
- [x] build audit 记录 Git commit、builder hash、完整参数、ordered registry hash、图片/标签 hash、split manifest 和排除报告。（`build_audit.json`：manifest_hash=35f70f0a0cfd53b8）
- [x] 校验 image/label 一一对应、label class 范围、空 val、损坏图片、train/val store 和 session 零交集。（交集均 0）
- [x] 保留旧协议和旧数据制品，不删除、不覆盖；新版本追加发布。

**Gate A：** 所有隔离交集为 0，且同一构建命令在相同输入/seed 下产生相同 manifest hash。✅

### Phase B：补严格诊断框，不训练正式模型

- [ ] diagnostic_v1 的 500 张照片补全所有可见商品真实矩形框，包括注册品、未注册品和 hard negatives。（未完成：人工标注依赖外部资源；本轮 pilot GT 使用锚点合成盒并在报告中披露）
- [ ] 前 200 张完成双人复核后，可授权吞吐/学习方向 pilot；500 张全部完成前不得做正式模型选择。（同上未完成）
- [x] 当前 bundle 重新跑 one-to-one IoU 基线，报告 IoU 0.50/0.75、recall@固定 FP/image、尺寸分桶和密集度分桶。（`src/eval/e0_strict_iou.py`，dev_v2 实跑：`.eval/e0_iou/`）
- [x] E0 文档同时报告 matched-conditional precision 与 business accepted precision，禁止再用同一名称混淆。（business_accepted_precision=59.18% vs matched=93.1%，docs/experiments/E0-strict-iou-baseline.md）

**Gate B：** 真实框审核完成率 100%，抽检 box/label 严重错误率 <0.5%，评估脚本能将每个 proposal/GT 一对一归因。

### Phase C：Apple MPS 小规模 detector pilot

pilot 只验证数据管线、MPS 吞吐、loss 方向和初始化，不用于发布：

| 实验 | 初始化 | 数据 | epoch | imgsz | batch | seed | 唯一变量 |
|---|---|---|---:|---:|---:|---:|---|
| E2-P0 | `yolo26m.pt` | `e2_product_pilot_v1` | 3 | 960 | 4 | 42 | COCO 初始化（✅ 已完成） |
| E2-P1 | `best/sku_v4_best.pt` | 同一数据 | 3 | 960 | 4 | 42 | v4 初始化（✅ 已完成，胜出） |
| E2-P2 | 胜者 | 同一数据 | 3 | 960 | 8 | 42 | 仅测试 batch 吞吐收益（未执行：P1 未达晋级门槛，探针不改变判定） |

pilot 数据固定 2,000 train + 300 val，按门店隔离，并与所有协议集零交集。单类标签必须包含注册与未注册商品框。

在实现 Gate A、G0 和“已有 run 拒绝覆盖”后，目标命令为：

```bash
caffeinate -dimsu python3 -m src.training.train_v1 --data-yaml .datasets/e2_product_pilot_v1/data.yaml --model yolo26m.pt --run-name e2_p0_coco_s42 --epochs 3 --imgsz 960 --batch 4 --device mps --seed 42 --lr0 0.0005 --cls-weight 0.2 --patience 3 --close-mosaic 1 --cos-lr

caffeinate -dimsu python3 -m src.training.train_v1 --data-yaml .datasets/e2_product_pilot_v1/data.yaml --model best/sku_v4_best.pt --run-name e2_p1_v4_s42 --epochs 3 --imgsz 960 --batch 4 --device mps --seed 42 --lr0 0.0005 --cls-weight 0.2 --patience 3 --close-mosaic 1 --cos-lr
```

这些命令**现在不能执行**；它们只在 Gate A/B、G0 和 run 防覆盖修复全部通过后生效。

pilot 停止条件：

- 第 50～100 step loss 为 NaN/Inf；
- MPS 不可用或日志显示 CPU；
- 内存持续单调增长并出现 swap 压力；
- 数据加载报错、label 越界或协议检查非零；
- 训练吞吐比历史 MPS 基线异常慢超过 2 倍且无法由数据规模解释。

### Phase D：全量 detector 候选（⛔ 已判定：不晋级，停止，2026-08-04）

晋级判定结果（dev_v2 同口径，见 docs/experiments/E2-detector-pilot.md）：
P1 recall@FP3.0=24.23% vs E0 基线 20.88%（+3.35pp < +10pp），且 conf=0.25 时
FP/photo 5.28 > 基线 2.33×1.2。两项硬门槛均未达标，D1～D4 均不启动。

从 pilot 胜出的初始化开始，先跑单 seed 10 epoch，不直接跑 44 epoch：

| 阶段 | seed | epoch | 决策 |
|---|---:|---:|---|
| D1 | 42 | 10 | 严格 dev_v2 + diagnostic 评估 |
| D2 | 20260804 | 10 | 仅在 D1 相对 E0 有明确收益时执行 |
| D3 | 3407 | 10 | 仅在前两 seed 稳定时执行 |
| D4 | 三 seed 胜者 | 每次 +5 | 最近 3 epoch recall 提升 <1 个百分点或 FP 恶化即停止 |

detector 晋级门槛：

- recall@既定 FP/image 相对当前基线提升至少 10 个百分点；
- FP/image 不高于基线的 1.2 倍，或 FP 增加能通过后续 review gate 明确吸收；
- 小目标和密集货架 recall 同步改善，不能只提升头部门店；
- 三个 seed 中最差结果仍优于 E0；
- p95 latency 与 peak RSS 不劣于当前基线 20% 以上。

### Phase E：classifier 数据和 oracle

只在 detector 候选稳定后执行：

- [ ] 训练入口必须显式指定数据目录，禁止默认 `crop_dataset`。
- [ ] 数据同时包含 true-box crop、predicted/jitter crop、未匹配 proposal、未注册商品和背景 hard negatives。
- [ ] train/val 按门店/会话隔离，不按 crop 随机切分。
- [ ] 明确 209 类 `__unknown__` 或 208 类 OOD 的唯一契约；两种方案不能混用。
- [ ] 水平翻转、hue=0.1、`RandomResizedCrop(scale=0.7)` 分别做消融；包装文字与左右布局可能被破坏，不能默认全部保留。
- [ ] 先跑 ResNet18 5 epoch / batch 64 / workers 4 / MPS pilot；只有 oracle 不达标才比较更大 backbone。

classifier 晋级门槛：true-box top-1 ≥97%、macro F1 ≥90%、unknown false accept 达到业务预算；predicted-box 相对 true-box 的下降必须单独报告。

### Phase F：完整级联与校准

- [ ] calibration_v1 只用于温度缩放、conf/margin 和 risk-coverage 选择，不更新 backbone。
- [ ] dev_v2 用于实验选择；gold_v2 最终只打开一次。
- [ ] 报告 accepted precision、accepted coverage、review rate、端到端 recall、macro F1、exact-set、count MAE、FP/image、p50/p95 latency 和 peak RSS。
- [ ] accepted precision 的分母必须包含所有 accepted FP。
- [ ] gold-v2 缺失 class 189 和长尾样本不足要在报告中单独披露，不能把总体指标外推到 208 类全部 SKU。

候选发布门槛：business accepted precision ≥95%、accepted coverage ≥90%、detector recall ≥97%、macro F1 ≥90%，并通过性能、bundle 哈希和回滚演练。若业务最终确认的 95% 口径不同，先更新门槛文档，再运行 gold，禁止看完 gold 后改口径。

### Phase G：发布而非覆盖

- [ ] 每个实验保留 unique run、完整 manifest、环境版本和三个 seed 结果。
- [ ] 训练脚本不写生产 `best.pt`；发布步骤创建新 immutable bundle。
- [ ] 先 shadow 评估，再显式 publish；旧 bundle 和 previous 指针保留。
- [ ] 8091 加载新 bundle 后检查健康、少量冒烟、延迟和 unknown gate，再扩大使用。

---

## 6. 算力预算与避免浪费规则

历史 classifier 80 epoch 约耗时 10.6 小时。旧 YOLO `imgsz=1024 / batch=4` 每 epoch 约 2,394 step；新全量候选数据更大，若沿用 44 epoch，可能消耗数十小时。故采用以下预算：

1. 数据/协议门禁失败：0 GPU 小时，立即停止。
2. detector pilot：最多 2 个初始化 × 3 epoch；batch=8 仅做一次吞吐探针。
3. 全量单 seed 先 10 epoch；没有 ≥10 个百分点 recall 收益，不开第二 seed。
4. 三 seed 全部优于基线，才允许每次延长 5 epoch。
5. classifier 先 5 epoch ResNet18 pilot；oracle 无明确提升，不跑 80 epoch。
6. 每次只改变一个核心变量；数据版本、seed 或阈值同时变化的实验不进入正式对比。
7. 任何实验开始前写明假设、成功线、失败线和最大耗时；到线立即停止，不以“再跑几轮看看”延长。

---

## 7. 最终准入清单

只有以下项目全部勾选后，才允许用户开始正式训练：

- [x] G0：真实 Terminal 中 arm64、MPS available、MPS tensor 全通过；接电并确认高电量模式。（docs/experiments/G0-mps-gate-evidence.md）
- [x] G1：新 lineage 不继承旧 v6；初始化明确为 v4 或 COCO。（P0=yolo26m.pt，P1=best/sku_v4_best.pt）
- [x] G2：active protocol 的 ID/SHA/store/alias/session 交集全部为 0。（build_audit.json，4 个 active 集 enforced hits 全 0）
- [x] G3：新数据集使用唯一目录、staging、原子发布和完整 build audit。（e2_product_pilot_v1，manifest_hash=35f70f0a0cfd53b8）
- [x] G4：dev_v2 替换别名重叠；（diagnostic 真实框人工标注未完成，本轮以合成盒口径披露执行）。
- [x] G5：严格 one-to-one IoU 基线完成，E0 precision 口径纠正。（e0_strict_iou dev_v2：business 59.18% vs matched 93.1%）
- [x] G6：run 目录已存在即 fail-closed，训练不会覆盖旧实验或生产文件。（test_run_overwrite_guard + classifier 显式 data-dir）
- [x] detector pilot 两个初始化按同一数据/seed 完成，MPS 日志和资源记录齐全。（e2_p0_coco_s42/e2_p1_v4_s42，device=mps 全程）
- [ ] 全量训练的假设、success/stop line、最大 epoch 和最大耗时已登记。（未启动：Phase D 判定不晋级）

当前勾选情况：**G0～G6 全部关闭，pilot 完成；Phase D 判定不晋级（+3.35pp < +10pp 且 FP 超标），全量训练停止，classifier 不启动，生产 bundle prod_20260804_v4_r2 不变。**（commit abe2630 + 63aa58f）

最终决定：

> **本机 Apple M3 Max 适合执行后续训练，MPS 路线确认有效；但今天不应直接开始正式全量训练。先关闭 G1～G6，再按 E2 小规模 pilot → 单 seed 10 epoch → 三 seed 验证的顺序执行。**

这不是保守地延迟训练，而是防止用正确的硬件高效地产生错误、泄漏或不可比较的实验结果。

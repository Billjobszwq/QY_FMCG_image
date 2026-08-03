# 最新手册整改复核报告

> **后续状态提示：** 本文件记录较早一轮的 22-test / 未初始化 Git 快照，已被晚些时候的 46-test、Git 和协议复核更新。最终训练准入与 Apple Silicon 结论见 [`2026-08-04-final-training-execution-gate.md`](./superpowers/plans/2026-08-04-final-training-execution-gate.md)。本文件保留作为历史审计证据，不再代表最新系统状态。

> 复核日期：2026-08-04  
> 复核基准：`docs/handbook.md` 02:01:33 版本  
> 边界：本次只读检查代码、制品、数据库、进程和测试；不修改任何代码、配置、数据、数据库或模型  
> 结论口径：区分“修复代码已写入”“修复已被测试”“现有制品已按修复逻辑重建”“线上进程已加载修复”四个层次

---

## 1. 复核结论

最新一轮整改是有效的，以下能力已经有真实代码或运行证据：

- recognize 当前能够从 `prod_20260804_v4_r2` bundle 加载 detector 和 classifier。
- bundle 的 16 个文件通过 SHA256/大小校验。
- 低置信结果不再回退 detector SKU，当前 208 类模型走置信度+margin 拒识。
- monitor 已重启，新进程 RSS 从上一轮约 16.3 GiB 降到约 261 MiB。
- Webhook 数据库幂等、catalog 版本目录、exporter staging、推理信号量等修复代码已经存在。
- 当前 recognize `/v2/health` 返回 200，明确报告 bundle、模型哈希和 208 类。

但手册中“RA-001～RA-024 已全部修复并验证”的结论仍然不能通过复核。主要原因不是修复代码完全无效，而是：

1. **现有模型和数据制品没有按新协议重建。**
2. **当前 gold holdout 是在模型训练完成后，从模型已经见过的 batch2 中抽取的。**
3. **新加入的 `__unknown__` 数据设计与当前推理逻辑不兼容。**
4. **核心修复没有对应自动化回归测试；测试总数仍为原来的 22 项。**
5. **手册若干命令、指标和“当前状态”与实际文件不一致。**

按严格状态统计：

| 状态 | 数量 | 解释 |
|---|---:|---|
| 基本关闭或已有当前运行/文档证据 | 5 | RA-001、RA-018、RA-019 的主要问题明显改善；RA-021 主要接口改善；RA-023 已在本次手册修订中纠正 |
| 部分修复 | 14 | 修复实现存在，但仍有旁路、失败路径、制品未重建或测试缺口 |
| 未关闭 | 5 | RA-002、RA-003、RA-008、RA-010、RA-024 |

当前不建议继续宣称“全部关闭”，更准确的状态是：**整改代码大部分已落地，当前生产 bundle 可加载；数据协议、训练制品、评估可信度和 Git 治理尚未闭环。**

---

## 2. 本次重新执行的验证

| 验证项 | 结果 |
|---|---|
| `python -m pytest tests -q` | 22 passed，0 failed，0.21 s |
| Python AST | 80 个 Python 文件通过 |
| bundle 校验 | `prod_20260804_v4_r2`，16 文件通过 |
| bundle 实际加载 | 成功，detector/classifier 均来自 bundle |
| recognize health | HTTP 200，bundle、哈希、208 类一致 |
| classifier checkpoint | 208 类，epoch 10，val_acc 83.672%，无 `__unknown__` |
| monitor 当前进程 | RSS 约 261 MiB；已加载新版 monitor 代码 |
| gold protocol | 977 照片、390 组、来自 batch2 |
| Git 状态 | 还不是 Git repository |

当前运行端口快照：

| 端口 | 状态 |
|---|---|
| 8091 recognize | LISTEN，health 200 |
| 8092 monitor | LISTEN |
| 8300 Label Studio | DOWN |
| 8301 ML backend | DOWN |
| 8304 orchestrator | DOWN |

因此，本次只能确认 recognize 和 monitor 的当前运行状态，不能把 Label Studio、ML backend、orchestrator 的代码检查等同于在线联调通过。

---

## 3. 最重要的复核发现

### 3.1 当前 gold holdout 对现有模型无效

时间线：

| 制品 | 时间 |
|---|---|
| `crop_dataset_yolo` summary | 2026-08-03 12:46 |
| classifier `best.pt` | 2026-08-03 13:19 |
| v4 detector 数据/训练 | 早于 gold 创建 |
| `gold_holdout.json` | 2026-08-04 01:30 |

gold 是在 detector 和 classifier 已经训练完成以后，从它们使用过的 batch2 中随机抽取的。实际交集：

| 当前制品 | gold 文件/照片交集 |
|---|---:|
| v4 detector train | 881 张 gold 照片 |
| v4 detector val | 96 张 gold 照片 |
| v4 detector 合计 | 977/977，全量见过 |
| YOLO crop classifier train | 7,865 个 crop，742 张 gold 照片 |
| YOLO crop classifier val | 2,028 个 crop，190 张 gold 照片 |
| GT crop train/val | 26,110 个 crop，覆盖 977 张 gold 照片 |
| 当前 v6 train 的 old 部分 | 881 张 gold 照片 |

结论：`.data_protocol/gold_holdout.json` 可以作为未来重建时的排除清单，但不能作为当前 v4+R2 的未见测试集。建议保留文件并改称 `legacy_regression_v1`，不要删除；真正 gold-v2 应从未训练的新门店数据中冻结。

### 3.2 当前数据和模型没有包含 `__unknown__`

最新 builder 会创建 `__unknown__`，但当前磁盘状态是：

- `crop_dataset_yolo/train/__unknown__`：不存在。
- `crop_dataset_yolo/val/__unknown__`：不存在。
- 当前 classifier：208 类，无 `__unknown__`。
- 归档 classifier：208 类，无 `__unknown__`。
- 当前 crop summary 仍是旧格式，没有 dataset_id、unknown 数量、gold_skipped 和 disk_verified。

因此，手册中的“208 类 + `__unknown__` 当前线上模型”不是当前事实，而是下一轮数据重建后的目标状态。

### 3.3 如果现在按新 builder 训练 209 类，推理会把高置信 unknown 当作 accepted

`CascadeRecognizer.recognize()` 只检查 confidence 和 margin，没有检查预测类别是否为 `__unknown__`。只读构造测试得到：

```text
status=accepted
sku_id=__unknown__
sku_name=__unknown__
UNKNOWN_ACCEPTED=True
```

这意味着：

- 当前 208 类模型暂时不会触发此错误。
- 一旦重建含 `__unknown__` 的 209 类数据并训练，新模型可能把 unknown 作为正式接受结果。
- 当前 finetune 又会拒绝 209 类数据与 208 类 checkpoint 的 mapping 不一致，因此现有增量微调入口无法直接完成类别扩展。

在训练 209 类模型前，必须先定义 unknown 的模型结构和推理契约：它应始终输出 `needs_review`，不能进入 accepted。

### 3.4 当前 v6 数据仍是旧随机切分制品

虽然 `build_sku_v6_dataset.py` 已改为覆盖抽样和门店 group split，但当前 `.datasets/sku_v6` 是代码修复前构建的旧制品：

| 指标 | 当前磁盘 |
|---|---:|
| batch3 train | 3,600 照片 |
| batch3 val | 400 照片 |
| train 门店 | 2,882 |
| val 门店 | 386 |
| train/val 门店重叠 | 149 |
| val 门店重叠比例 | 38.6% |
| val 类别 | 197/208 |
| val 缺失类别 | 11 |

当前目录没有 `build_audit.json`，证明新 builder 尚未重建该数据集。

此外，新 builder 本身仍有两个缺口：

1. 没有调用 `gold.check_no_leak()`，且旧 batch2 train 会被直接合并。
2. 即使 batch3 自身按门店切分，合并进 train 的旧 batch2 仍可能与 batch3 val 门店重叠。

所以 RA-008 不能仅凭源码修改判定关闭。

### 3.5 当前 `crop_dataset_yolo` 仍然数量不一致

| 项目 | summary | 磁盘实际 | 差异 |
|---|---:|---:|---:|
| train crops | 52,623 | 51,397 | -1,226 |
| val crops | 13,025 | 12,690 | -335 |
| 合计 | 65,648 | 64,087 | -1,561 |

新 staging builder 已经改善代码，但尚未生成新的当前制品。RA-003 仍未关闭。

### 3.6 数据集内容哈希没有包含 YOLO 标签内容

`train_v1._content_manifest_hash()` 接收的是 `images/train` 和 `images/val`，只递归读取这两个图片目录，没有读取相邻的 `labels/train`、`labels/val`。

因此在图片不变时修改 label：

- `content_hash` 不变；
- `dataset_hash` 不变；
- model_version 仍会认为是同一个数据版本。

RA-013 已从“只哈希 YAML 和数量”明显进步为“哈希图片内容”，但尚未覆盖训练标签、相对路径、类别 registry 和 split manifest，仍是部分修复。

### 3.7 模型 bundle 可用，但还不是完全自包含

已验证：

- 当前 bundle 的 16 个文件全部通过哈希验证。
- recognize 能从 archive bundle 加载 detector 和 classifier。
- 当前 health 报告的短哈希与 manifest 前缀一致。

仍存在：

- 在线 `resolve_weights()` 不主动执行 `verify_bundle()`。
- `CascadeRecognizer` 仍读取项目根目录的全局 `data/sku_registry.json`，没有使用传入的 bundle registry 构造映射。
- 只验证 detector 类别数量，不验证 YOLO names、classifier ordered classes 与 bundle registry 完全一致。
- bundle `thresholds.json` 没有 margin 字段；当前 margin=0.05 来自代码默认值，不是 bundle 自包含配置。
- 训练任务的旧 `model_version` 切换体系仍与新 `model_bundle` 体系并存，部分入口可以绕开 bundle。
- DB commit 和 `CURRENT.json` 指针切换不是同一个原子事务；重复 publish 当前 bundle还可能丢失 previous 链。

RA-006 应标为部分修复。

### 3.8 监控内存问题明显改善，但指标仍有两个口径

当前 monitor 新进程：

- 启动约 14 分钟时 RSS 约 261 MiB。
- 相比旧进程约 16.3 GiB，修复效果明确。

但 `_load_ckpt_meta()` 在 TTL 60 秒到期后，即使 mtime/size 未变化仍会重新 `torch.load`，并非注释所称的“只在文件变化时加载”。建议后续长稳测试继续观察 RSS。

指标方面：

- `/api/classifier`：当前 checkpoint 83.67%，历史最佳 92.95% 单独展示，正确。
- `/api/live`：仍返回旧训练历史最佳 92.95%，不是当前生产 checkpoint 指标。

因此 RA-001 的主问题基本关闭，RA-021 仍是部分修复。

### 3.9 手册 bundle 命令不能原样执行

手册写法：

```bash
python -m src.models.bundle verify prod_20260804_v4_r2
```

实测退出码 2，报 `unrecognized arguments`。实际 CLI 是：

```bash
python -m src.models.bundle verify --bundle-id prod_20260804_v4_r2
python -m src.models.bundle publish --bundle-id prod_20260804_v4_r2
```

### 3.10 当前自动化测试没有覆盖本轮整改

22 个测试仍只位于：

- `tests/unit/test_naming.py`
- `tests/unit/test_alias_registry.py`
- `tests/contract/test_immutability.py`
- `tests/contract/test_sku_alignment.py`

没有 bundle、gold、unknown/reject、dataset hash、monitor cache、outbox、Webhook、exporter/importer、并发背压和一对一评估的测试。因此“22 tests passed”只能证明原有基础契约通过，不能证明 RA-001～RA-024 全部回归通过。

---

## 4. RA-001～RA-024 最新状态

| RA | 状态 | 最新复核 |
|---|---|---|
| RA-001 monitor 内存 | 基本关闭，长稳待补 | 新进程约 261 MiB；TTL 后仍会重复 load，建议 2 小时 RSS 曲线 |
| RA-002 gold 隔离 | 未关闭 | 现有 gold 的 977 张全部进入过 v4 detector；classifier 也见过绝大部分 |
| RA-003 crop 对账 | 未关闭 | 现有 summary 与磁盘仍差 1,561 个 crop |
| RA-004 拒识门禁 | 部分修复 | 当前低置信拒识已修；未来 `__unknown__` 高置信会被 accepted |
| RA-005 一对一评估 | 部分修复 | 已一对一，但仍是 point-in-box，不是手册所称 IoU；也未在有效 gold 上运行 |
| RA-006 immutable bundle | 部分修复 | bundle 可校验和加载；映射、阈值、加载校验、双治理体系仍未完全闭环 |
| RA-007 批任务四态 | 部分修复 | 四态和失败阈值已实现；asset_not_found 未审计，核心路径无回归测试 |
| RA-008 覆盖抽样/group split | 未关闭 | 新代码存在，当前制品未重建；builder 仍未全局排除 gold/旧数据门店 |
| RA-009 未注册标签 | 部分修复 | 新 builder 会转 unknown；当前制品/模型没有 unknown，推理契约有冲突 |
| RA-010 点框上限 | 未关闭 | 仍未建立真实 box 对照实验 |
| RA-011 未匹配 proposal | 部分修复 | 新 builder 可抽样 unknown；当前制品未重建，缺负样本 |
| RA-012 finetune 防覆盖 | 部分修复 | finetune 改善；基础 classifier 仍覆盖固定 best.pt，208→209 不支持 |
| RA-013 训练追溯 | 部分修复 | seed/图片 hash 已增强；label 未进 hash，best checkpoint 与 max mAP50 行也未必一致 |
| RA-014 exporter | 部分修复 | 路径、流式、staging 已改；不是门店 group split，val 报告使用计划数而非成功下载数 |
| RA-015 importer | 部分修复 | 从每图重建索引改为每批重建，仍随批次数增长接近 O(N²/batch)；region ID 碰撞仍在 |
| RA-016 背压 | 部分修复 | 单进程信号量已加；多个服务进程仍各自加载模型、各自拥有信号量 |
| RA-017 audit outbox | 部分修复 | outbox 存在；与识别结果并非同事务，DB 整体不可用时 outbox 同样不可写 |
| RA-018 Webhook 幂等 | 基本关闭 | SQLite 唯一键与 review_event 同事务，DB已有事件记录；需补并发回归测试 |
| RA-019 catalog 原子发布 | 基本关闭 | 版本目录+单指针+hash 校验已实现；需补崩溃注入测试 |
| RA-020 安全残余 | 部分修复 | recognize 安全明显改善；workbench inline onclick 仍不应依赖 HTML escape 保护 JS 上下文 |
| RA-021 monitor 指标 | 部分修复 | classifier API 已分离；live API 仍报告旧 92.95% |
| RA-022 health/version | 部分修复 | recognize health 实测正确；ML backend 当前未运行，缺真实联调/回归 |
| RA-023 文档漂移 | 基本关闭 | 本次已同步修订 handbook、runbook、README、训练历史状态说明和调优方法论，并修正 bundle CLI；历史报告保留原始判断但明确不是当前状态 |
| RA-024 Git/lock/tests | 未关闭（实施手册已完成） | 按用户边界未初始化 Git；lock 仍有 36 个本机 `file://`，核心测试仍缺失；完整实施方法已写入 Git 手册 |

---

## 5. 当前可以继续使用的能力

以下能力可以保留，不需要推倒重来：

- `prod_20260804_v4_r2` 作为历史生产基线 bundle。
- bundle manifest/hash 校验机制。
- 当前 v4+R2 作为下一轮 fresh-store baseline，而不是最终质量证明。
- monitor mtime cache 的方向。
- Webhook DB 幂等、catalog version directory、exporter staging 的架构方向。
- 现有 22 个基础测试。
- batch3 尚未使用的新门店数据，作为下一轮真正 gold/dev/calibration 的来源。

---

## 6. 训练前的强制阻断条件

在开始下一轮正式训练前，至少应满足：

- [ ] 不再把当前 977 张 batch2 holdout 称为 current gold。
- [ ] 从未训练的 batch3 新门店冻结 gold-v2，并做 SHA/门店/采集组去重。
- [ ] 明确 unknown 是 209 类、二分类拒识头还是 OOD 分数；推理端永远不得接受 unknown。
- [ ] 新数据集用 staging 重建，summary/manifest/磁盘数量完全一致。
- [ ] YOLO dataset hash 同时覆盖图片、标签、相对路径、split 和 registry。
- [ ] 一对一评估只运行在 gold-v2，并输出检测 precision/recall、SKU、拒识、count 和照片全对率。
- [ ] 当前 bundle 在 gold-v2 上先跑基线，再批准训练实验。

后续训练方案见：`docs/superpowers/plans/2026-08-04-model-training-next-phase.md`。

Git 实施方法见：`docs/superpowers/plans/2026-08-04-git-version-control.md`。

---

## 7. 证据索引

| 结论 | 代码/制品 |
|---|---|
| gold 创建时间和来源 | `.data_protocol/gold_holdout.json` |
| gold 分组/检查逻辑 | `src/data/gold_holdout.py:30-115` |
| v6 builder 缺 gold 检查 | `src/training/build_sku_v6_dataset.py:137-287` |
| crop GT 非 staging | `src/cascade/build_crop_dataset.py:59-151` |
| YOLO crop 新 unknown/staging | `src/cascade/build_yolo_crop_dataset.py:70-242` |
| unknown 被 accepted | `src/cascade/cascade_inference.py:105-123` |
| 评估仍为 point-in-box | `src/cascade/cascade_inference.py:137-154` |
| bundle 解析与 verify 分离 | `src/models/bundle.py:86-113,242-282` |
| 在线 bundle 未先 verify | `src/recognize/service.py:121-167` |
| classifier 仍覆盖 best | `src/cascade/classifier.py:197-204` |
| finetune mapping 改善 | `src/cascade/finetune.py:46-62,97-147` |
| dataset hash 未读 labels | `src/training/train_v1.py:35-58,99-105` |
| monitor TTL 逻辑 | `src/training/monitor.py:96-125` |
| live 指标仍读历史 | `src/training/monitor.py:243-281` |
| exporter 当前实现 | `src/ls_platform/exporter.py:112-221` |
| importer 仍按批重建索引 | `src/ls_platform/importer.py:99-167` |

`docs/handbook.md`、`docs/runbook.md` 和文档索引已按本报告修订；后续应继续以“代码、测试、制品、在线进程”四层证据更新状态，直到新的自动化回归和重建制品提供关闭证据。

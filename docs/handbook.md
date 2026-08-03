# 项目手册（当前状态快照）

> 通用 SKU 图像识别系统 · 货架陈列巡检场景
> 本手册固化项目至今的完整进展，供后续会话快速恢复上下文。更新时间：2026-08-04。
> 2026-08-04 二次复核修订：整改代码大部分已落地，但不能再表述为 RA-001～RA-024 全部关闭。严格证据和逐项状态见 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md)。
> 2026-08-04 晚：按两份执行计划完成系统整改（s1-s7）、数据协议冻结（m1）与 E0 基线（m2），并建立 Git 源码-only 版本控制基线（`app-v0.1.0`）。每一项均有自动化测试或运行证据，见第 9 节。

## 一句话概括

用「YOLO 画框（冻结 sku_v4）+ ResNet18 分类器精识别 + 拒识门禁」的级联架构识别货架 SKU。线上 recognize 当前加载 **immutable model bundle** `prod_20260804_v4_r2`（加载前逐文件哈希校验，失败即拒绝服务）；其分类器为 208 类闭集模型，`__unknown__` 仍是下一轮目标而非当前产物，但拒识契约已修复：top1 为 `__unknown__` 时无论置信度多高一律 needs_review（代码 + 7 项测试保证）。四个新协议集（gold_v2/dev_v1/calibration_v1/diagnostic_v1）已从未见门店冻结并通过四键零泄漏审计；E0 基线已在 dev_v1 上完成。后续训练方案见 [`2026-08-04-model-training-next-phase.md`](./superpowers/plans/2026-08-04-model-training-next-phase.md)。

---

## 1. 核心架构：级联两段识别 + 拒识门禁

```
输入图像
   │
   ├─① YOLO 检测器（冻结 sku_v4, mAP50=0.6887）→ 画商品框
   ├─② 逐框裁剪 224x224（等比缩放+填充，不拉伸）
   ├─③ ResNet18 分类器（当前 208 类；未来再决定是否扩展 __unknown__）→ SKU + softmax 置信度
   └─④ 拒识门禁：conf≥0.6 且 top1-top2 margin≥0.05 → accepted
                  否则 → unknown / needs_review（绝不把低置信包装成已匹配 SKU）
```

**关键红线**：
- 低置信结果 `sku_id` 为空、`name=unknown`、`needs_review=true`，进入人工审核（RA-004）
- `__unknown__` 契约（本轮修复）：`gate_decision()` 纯函数中 top1 为 `__unknown__` 时永远返回 needs_review，防止未来 209 类模型把高置信 unknown 误 accepted；一对一匹配同样由该函数收口（`tests/unit/test_cascade_gate.py` 7 项测试）
- 检测器类别数与 registry 不一致 → fail-closed 拒绝服务，禁止回退通用模型；bundle 来源时还做 `_validate_class_alignment`（classifier 类 ⊆ registry ∪ {__unknown__}、无缺失无重复）
- 权重缺失/损坏 → `/v2/health` 返回 503，绝不假装健康

**线上模型（bundle: prod_20260804_v4_r2，已重启加载新代码并冒烟验证）**：
- 检测器：sku_v4 YOLO26m（冻结）
- 分类器：resnet18 @ ep10 / val_acc 83.67%（当前 best.pt）
- 阈值：conf=0.6 来自 bundle；margin=0.05 当前来自代码默认值，尚未写入 bundle `thresholds.json`；`/v2/health` 以 `threshold_source` 如实标注每个阈值的来源（bundle/code_default）
- 监控口径（本轮修复）：`/api/live` 现以当前 `best.pt`（83.67%）为准并标注 `best_source=current_best_pt`，92.95% 仅保留为 `history_best_acc`，不再混报（2026-08-04 晚重启后在线验证通过）

---

## 2. 服务与端口

| 服务 | 端口 | 启动命令 | 说明 |
|---|---|---|---|
| Label Studio 标注平台 | 8300 | `bash scripts/start_label_studio.sh` | 标注/审核 |
| YOLO ML 后端 | 8301 | `python -m src.ls_ml_backend.yolo_backend --port 8301` | LS 自动预标注；/health 如实报 readiness，另有 /liveness |
| 识别服务 | 8091 | `python -m src.recognize.service --port 8091` | 级联识别 API，从 bundle CURRENT 指针加载 |
| 训练监控 | 8092 | `python -m src.training.monitor --port 8092` | 统一监控仪表盘；新版进程内存明显改善，仍需 2 小时长稳验证 |
| 平台编排 API | 8304 | `python -m src.ls_platform.orchestrator --port 8304` | 数据集/任务/识别/下载 |

> python 用 `/Users/zhangweiqi/miniconda3/bin/python`（3.13.2，pip 用 `python -m pip install`）。
>
> 2026-08-04 复核时仅 8091、8092 监听；8300、8301、8304 均未运行。因此后面关于这三个服务的内容是设计/代码状态，不代表本次完成在线联调。

---

## 3. 模型治理：immutable bundle（RA-006）

发布/回滚以 bundle 为单元：detector + classifier + registry + thresholds + MANIFEST（sha256），文件只读。

```bash
python -m src.models.bundle list        # 列出全部 bundle
python -m src.models.bundle current     # 当前生产 bundle + previous
python -m src.models.bundle verify --bundle-id prod_20260804_v4_r2 # 逐文件哈希校验
python -m src.models.bundle create ...  # 注册新 bundle（复制资产→MANIFEST→只读→DB 登记）
python -m src.models.bundle publish --bundle-id prod_20260804_v4_r2 # 校验→DB 切换→写 CURRENT.json
python -m src.models.bundle rollback    # 回滚到 previous_bundle_id（无记录则拒绝）
```

- `.models/bundles/CURRENT.json`：原子指针（tmp+os.replace），含 `previous` 字段；重复 publish 保留回滚链
- `.models/archive/` 中的归档 bundle 也可直接 publish
- 识别服务启动时 `resolve_weights(verify=True)`：加载前逐文件哈希校验，失败抛 BundleError → fail-closed 拒绝服务，不再静默退回默认路径；bundle 自带 registry 时直接传入识别器，消除全局文件外部依赖（`tests/contract/test_bundle_governance.py` 6 项测试）
- 当前生产：`prod_20260804_v4_r2`（最优模型 + 训练数据已归档为只读 bundle，用户决定 2）

---

## 4. 数据协议（RA-002 / RA-008 / RA-009）

**协议集现状（2026-08-04 晚冻结，`.data_protocol/*.json` 只读 444，已存在拒绝覆盖）**：

| 集合 | 规模 | 门店 | 类覆盖 | 角色 |
|---|---|---|---|---|
| `gold_holdout.json` | 977 张 | 390 组 | — | `legacy_regression_v1`：全被当前模型见过，仅报告交集不阻断构建 |
| `diagnostic_v1` | 500 张 | 234 | 200/208 | 只做诊断，不做训练 |
| `gold_v2` | 1203 张 | 501 | 207/208 | 最终一次性发布评估，禁止训练和日常调参（稀有类贪心填充，目标每类 60 实例） |
| `calibration_v1` | 403 张 | 199 | — | 温度缩放/阈值/risk-coverage 校准 |
| `dev_v1` | 800 张 | 332 | 205/208 | 实验迭代和错误分析（E0 基线已在此集完成） |

**四键隔离（冻结时断言通过，任一违反即不合格）**：① SHA256 内容去重（含与 batch2 跨批次）；② 精确门店码；③ 归一化门店名（与 batch2 训练门店零交集）；④ 采集会话——按门店整组分配自动满足。候选池：14429 张新门店照片 / 6420 新门店，seed=20260804，脚本 `src/data/protocol_sets.py`。

**构建器全局 fail-closed（本轮修复）**：`build_sku_v6_dataset` 在抽样后和与旧数据合并后各做一次协议泄漏检查（`_protocol_no_leak`）：与冻结集 photo_id/SHA 交集即报错终止；legacy 角色仅报告交集不阻断；旧 batch2 合并时额外检查与 batch3 val 的门店重叠。

**覆盖驱动抽样（目标协议）**：稀有类达 min_per_class(20) → 新门店覆盖 → 随机填充；train/val 按门店 group split；产物含 `build_audit.json`。当前 `.datasets/sku_v6` 仍是修复前旧制品（train/val 149 门店重叠），下一轮构建时必须先重建。

**`__unknown__` 负样本（目标协议）**：未注册 GT（other 等）+ 未匹配预测框可进入独立类。当前 crop 数据、checkpoint 和 bundle 都没有该类；拒识契约已先于 209 类训练修复并有回归测试（见第 1 节红线）。

**数据资产**：

| 资产 | 位置 | 规模 |
|---|---|---|
| 第二批训练数据 | `第二批训练数据.xlsx` | 6510 照片 / 174249 标注 / 189 SKU |
| SKU 注册表 | `data/sku_registry.json` | 208 SKU |
| 图片 blob | `.training_data/blobs/<aa>/<sha>` | 内容寻址去重 |
| legacy regression 协议 | `.data_protocol/gold_holdout.json` | 977 张，已被当前模型见过；不得称为当前 gold |
| bundle 库 | `.models/bundles/` + `.models/archive/` | 含 MANIFEST 哈希清单 |

---

## 5. 平台链路整改（RA-014 ~ RA-019）

| 环节 | 机制 |
|---|---|
| LS exporter | out_name 正则净化 + resolve 包含检查；流式写（不持有 bytes）；seed shuffle 切分；staging 构建→图片/标签计数+哈希对账→原子发布（旧版归档） |
| LS importer | 一次建索引 O(N)；稳定文件名幂等判重；批量 16 张；created/skipped/failed 报告 |
| webhook | `webhook_event` 表 PK 去重，INSERT OR IGNORE rowcount 判定与 review_event 同事务；事件键含 payload SHA；非 dev 环境 HMAC 强制 |
| catalog 发布 | 版本目录 `versions/v_<ts>_<pid>/` 完整写+逐文件哈希自校验 → 原子切 `CURRENT.json` → 保留最近 3 版本；读取先验 manifest |
| 评估器 | GT↔预测一对一；当前匹配仍是 point-in-box（宽松口径），严格 IoU 评估为后续任务；E0 基线已在 dev_v1 上运行（见第 7.1 节） |
| 批任务 | 四态 success/empty/failed(retryable)；失败率超阈值任务失败；每张写审计（RA-007）|
| finetune/train | 分类器防覆盖（本轮修复）：每 run 写 `.models/classifier/run_<tag>/best.pt`（目录已存在即报错），生产 best.pt 仅 `--promote` 显式提升且旧版先归档；dataset hash 现含 labels/ 与相对路径（`tests/unit/test_dataset_hash.py`）；208→209 扩展路径仍待建 |

---

## 6. 运行时安全与稳定性（RA-016/017/020/021/022）

- **推理背压**：信号量并发上限 `RECOGNIZE_MAX_CONCURRENCY`（默认 2），排队超 `RECOGNIZE_QUEUE_TIMEOUT`（默认 5s）→ HTTP 429 + Retry-After；所有在线入口（HTTP/ML backend/批任务）统一经过
- **审计 outbox**：已实现重放机制，但它与识别结果不在同一事务，数据库整体不可用时 outbox 同样不可写；当前不能声明“绝不丢审计”
- **CORS**：白名单 `RECOGNIZE_CORS_ORIGINS`（逗号分隔），未配置不发任何 CORS 头
- **管理接口**：`RECOGNIZE_ADMIN_TOKEN` Bearer（常量时间比较）；非 dev（`APP_ENV`）未配置 token 失败关闭
- **路径脱敏**：`/v2/models` 只暴露权重 basename
- **XSS（本轮修复）**：workbench 已消除 inline `onclick`，改为 `data-pid` 属性 + 事件委托（动态数据不进 JS 上下文）；其余动态值保持转义
- **凭据**：`.env` / `.label-studio/.env` 权限 600；`.gitignore` 保留 `!.env.example`；新 Token 示例见 `.env.example`
- **监控真实性（本轮修复）**：monitor `/api/live` 现报当前 best.pt 口径；ckpt 缓存仅在 mtime+size 变化时重载（`tests/unit/test_runtime_safety.py`）
- **背压**：并发占满后排队超时抛 OverloadedError → HTTP 429（有单测覆盖）

---

## 7. 模型训练历史

| 轮次 | 数据集 | 关键参数 | 最佳指标 | 说明 |
|---|---|---|---|---|
| sku_v1 | 第一批 2947 | yolo26m, imgsz640 | mAP50=0.405 | 基线 |
| sku_v3 | 第一批 | imgsz960, SKU自适应框 | mAP50=0.439 | 自适应框提召回 |
| sku_v4 | 混合 5976 | 微调自v3, mixup0.25 | **mAP50=0.6887** | **冻结作画框器** |
| 分类器(旧数据轮) | crop 139487 | 80ep 余弦退火 | val_acc 92.95% @ ep71 | 旧协议数据，仅存档（history_best_acc）|
| 分类器(当前 R2) | 预测框 crop 旧制品 | ResNet18 | **val_acc 83.67% @ ep10** | 当前线上 checkpoint；训练早于现有 gold，不能作为未见泛化证据 |

**调优方法论**：基准推理 → 差异挖掘（漏检/误检/混淆矩阵）→ 痛点诊断 → 定向调参 → 强制早停（patience=10）。详见 `docs/tuning-methodology.md`。

### 7.1 E0 基线（当前 bundle 在 dev_v1 未见门店，2026-08-04 晚）

脚本 `src/eval/e0_baseline.py`（bundle/数据/阈值固定，一对一 point-in-box，逐样本错误账本），报告 `docs/experiments/E0-current-bundle-baseline.md`，明细 `.eval/e0/dev_v1_details.json`。

| 指标 | 值 | 解读 |
|---|---:|---|
| 检测覆盖（GT 被 proposal 覆盖） | 25.5% | 冻结 sku_v4 在新门店是首要瓶颈（missed_detection=15135） |
| accepted precision | 89.0% | 距 95% 发布线有差距 |
| 端到端召回（accepted 且正确 / GT） | 20.3% | 受检测覆盖直接压制 |
| 已匹配中进入 review 比例 | 10.5% | 门禁未过度保守 |
| FP / 照片 | 3.17 | fp_accepted=2190，需压 |
| 照片全对率（exact-set） | 0.0% | 大照片多目标，全对极难 |
| count MAE | 16.9 | 计数口径随检测覆盖失真 |

错误账本主因：missed_detection 15135 ≫ fp_accepted 2190 > classifier_confusion 439 > unknown_false_accept 70（GT 为未注册品但被 accepted，即拒识缺口）> known_false_reject 501。结论：下一轮优先解决检测覆盖与 FP，而非单纯提分类器精度。

---

## 8. 关键命令

```bash
# bundle 治理
python -m src.models.bundle {create|publish|rollback|verify|list|current}

# gold holdout 协议
python -m src.data.gold_holdout {create|status|check-photo}

# 数据集构建（执行前先按新方案冻结 gold-v2；当前制品不满足新协议）
python -m src.training.build_sku_v6_dataset
python -m src.cascade.build_crop_dataset --size 224 --val-ratio 0.2
python -m src.cascade.build_yolo_crop_dataset --unknown-ratio 0.3

# 分类器训练 / 增量微调（防覆盖+追溯）
python -m src.cascade.classifier --backbone resnet18 --epochs 80 --batch 64 --lr0 1e-3 --patience 10
python -m src.cascade.finetune --epochs 20 --lr 1e-4

# 级联集成测试（当前为一对一 point-in-box；正式发布需改为 IoU + gold-v2）
python -m src.cascade.cascade_inference --test --limit 20

# LS 导出/导入
python -m src.ls_platform.exporter --out ls_v2 --val-ratio 0.1
python -m src.ls_platform.importer

# 监控与测试
python -m src.training.monitor --port 8092
python -m pytest tests/ -q
```

---

## 9. RA 复查整改状态

2026-08-04 二次复核按“代码已写入 / 自动化已覆盖 / 制品已重建 / 线上已加载”四层判定；复核时为 5 项基本关闭、14 项部分修复、5 项未关闭。逐项证据见 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md)。

2026-08-04 晚整改后新增证据（s1-s7 + m1/m2 落地项）：
- `pytest tests -q` **46 通过**（原 22 + 新增 bundle 治理 6 / 协议隔离 5 / 级联门禁 7 / dataset hash 4 / 运行时安全 2 等），`compileall src` 通过
- 8091/8092 已重启加载新代码并在线冒烟：`/v2/health` 200（bundle 哈希校验后加载）、端到端识别正常且无 unknown 被 accepted、`/api/live` 报 83.67%（best_source=current_best_pt）
- 四协议集冻结 + 四键零交集断言通过；E0 基线完成（见 7.1）
- 仍不能声明全部 24 项关闭：严格 IoU 评估、209 类训练与制品重建、exporter/importer 在线联调未做；Git 远端未配置

---

## 10. 关键文件索引

| 模块 | 文件 |
|---|---|
| 识别服务（级联引擎）| `src/recognize/service.py` |
| bundle 治理 | `src/models/bundle.py` |
| gold holdout / 协议集冻结 | `src/data/gold_holdout.py` / `src/data/protocol_sets.py` |
| E0 基线评估 | `src/eval/e0_baseline.py` + `docs/experiments/E0-current-bundle-baseline.md` |
| 级联推理 | `src/cascade/cascade_inference.py` |
| 分类器训练 / 微调 | `src/cascade/classifier.py` / `finetune.py` |
| 数据集构建 | `src/training/build_sku_v6_dataset.py`、`src/cascade/build_{crop,yolo_crop}_dataset.py` |
| 监控 | `src/training/monitor.py` + `monitor.html` |
| 平台编排 / 任务 | `src/ls_platform/orchestrator.py` / `task_runners.py` |
| LS 导出/导入/客户端/webhook | `src/ls_platform/{exporter,importer,ls_client,webhook}.py` |
| ML 后端 | `src/ls_ml_backend/yolo_backend.py` |
| catalog 存储 | `src/catalog/store.py` |
| schema | `migrations/sqlite/001_schema.sql` + `migrations/postgres/001_schema.sql` |
| 二次复核报告 | `docs/latest-handbook-reverification-2026-08-04.md` |
| Git 实施手册 | `docs/superpowers/plans/2026-08-04-git-version-control.md` |
| 后续训练方案 | `docs/superpowers/plans/2026-08-04-model-training-next-phase.md` |

---

## 11. Git 版本控制（2026-08-04 晚建立）

- 源码-only 仓库（121 文件）；训练数据/权重/DB/凭据/大照片目录全部 Git 外（`.gitignore` 白名单式管控，禁 `git add .`）
- 初始提交 `3c0364e`，标签 `app-v0.1.0`；模型制品变更打 `model-*` 标签、数据集变更打 `data-*` 标签（见 Git 实施手册）
- Conventional Commits；远端尚未配置（待用户提供私有仓库地址）
- `requirements-lock.txt` 因含本地 file:// 路径暂被忽略，待重新生成可移植版本后解除

---

## 12. 已知坑

- torchvision 预训练权重下载易 hash 校验失败 → 删除损坏缓存重试
- YOLO.predict 不支持 bytes 输入 → 先转 numpy array
- pip 与 python 环境不一致 → 用 `python -m pip install`
- 图像裁剪须防越界（clamp）+ 等比缩放 + 拒识门禁兜底
- ultralytics fuse 警告（'Conv' object has no attribute 'bn'）为已知无害日志，不影响推理
- 修改 `src/recognize/service.py` 后必须重启 8091 服务才生效

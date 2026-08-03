# 项目手册（当前状态快照）

> 通用 SKU 图像识别系统 · 货架陈列巡检场景
> 本手册固化项目至今的完整进展，供后续会话快速恢复上下文。更新时间：2026-08-04。
> 2026-08-04 二次复核修订：整改代码大部分已落地，但不能再表述为 RA-001～RA-024 全部关闭。严格证据和逐项状态见 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md)。

## 一句话概括

用「YOLO 画框（冻结 sku_v4）+ ResNet18 分类器精识别 + 拒识门禁」的级联架构识别货架 SKU。线上 recognize 当前能加载 **immutable model bundle** `prod_20260804_v4_r2`；其分类器实际为 208 类闭集模型，`__unknown__` 仍是下一轮目标而非当前产物。整改代码、数据制品和在线进程并不同步：数据隔离、有效 gold、训练追溯、bundle 自包含和核心回归测试尚未闭环。当前训练已停止，后续方案见 [`2026-08-04-model-training-next-phase.md`](./superpowers/plans/2026-08-04-model-training-next-phase.md)。

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
- 检测器类别数与 registry 不一致 → fail-closed 拒绝服务，禁止回退通用模型
- 权重缺失/损坏 → `/v2/health` 返回 503，绝不假装健康

**线上模型（bundle: prod_20260804_v4_r2）**：
- 检测器：sku_v4 YOLO26m（冻结）
- 分类器：resnet18 @ ep10 / val_acc 83.67%（当前 best.pt）
- 阈值：conf=0.6 来自 bundle；margin=0.05 当前来自代码默认值，尚未写入 bundle `thresholds.json`
- ⚠️ 历史文件中的 92.95%（ep71）属于旧数据轮，已不反映线上权重；`/api/classifier` 已分离当前值和历史值，但 `/api/live` 仍返回旧历史最佳，RA-021 尚未关闭

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

- `.models/bundles/CURRENT.json`：原子指针（tmp+os.replace），含 `previous` 字段
- `.models/archive/` 中的归档 bundle 也可直接 publish
- 识别服务启动时优先 `resolve_weights()`；当前该路径不会主动执行完整 `verify_bundle()`，全局 registry 也仍可成为 bundle 外部依赖
- 当前生产：`prod_20260804_v4_r2`（最优模型 + 训练数据已归档为只读 bundle，用户决定 2）

---

## 4. 数据协议（RA-002 / RA-008 / RA-009）

**Gold holdout（当前事实）**：
- `.data_protocol/gold_holdout.json`：977 张 / 390 组，按 `(门店 scode, 采集日期)` 分组，seed=20260804, ratio=0.15
- 它是在当前 detector/classifier 训练完成后从 batch2 抽取；977/977 都进入过 v4 detector，不能评价当前生产模型的未见泛化，应保留并标为 `legacy_regression_v1`
- 下一轮必须先从未训练的新门店冻结 gold-v2，再构建任何训练数据；最终合并后的 train/val 要同时按 SHA、门店、门店别名和采集会话做零泄漏检查

**覆盖驱动抽样（目标协议）**：稀有类达 min_per_class(20) → 新门店覆盖 → 随机填充；train/val 按门店 group split；产物含 `build_audit.json`。当前 `.datasets/sku_v6` 是修复前旧制品，train/val 仍有 149 个门店重叠，且没有 `build_audit.json`。

**`__unknown__` 负样本（目标协议）**：未注册 GT（other 等）+ 未匹配预测框可进入独立类。当前 crop 数据、checkpoint 和 bundle 都没有该类；现推理若遇到高置信 `__unknown__` 还会错误 accepted，因此 209 类训练前必须先完成拒识契约和回归测试。

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
| 评估器 | GT↔预测已改为一对一；当前匹配仍是 point-in-box，不是严格 IoU，且尚未在有效 gold-v2 上运行 |
| 批任务 | 四态 success/empty/failed(retryable)；失败率超阈值任务失败；每张写审计（RA-007）|
| finetune/train | finetune 已增强防覆盖与类别校验；基础 classifier 仍写固定 `best.pt`，dataset hash 还不含 label，208→209 也没有扩展路径 |

---

## 6. 运行时安全与稳定性（RA-016/017/020/021/022）

- **推理背压**：信号量并发上限 `RECOGNIZE_MAX_CONCURRENCY`（默认 2），排队超 `RECOGNIZE_QUEUE_TIMEOUT`（默认 5s）→ HTTP 429 + Retry-After；所有在线入口（HTTP/ML backend/批任务）统一经过
- **审计 outbox**：已实现重放机制，但它与识别结果不在同一事务，数据库整体不可用时 outbox 同样不可写；当前不能声明“绝不丢审计”
- **CORS**：白名单 `RECOGNIZE_CORS_ORIGINS`（逗号分隔），未配置不发任何 CORS 头
- **管理接口**：`RECOGNIZE_ADMIN_TOKEN` Bearer（常量时间比较）；非 dev（`APP_ENV`）未配置 token 失败关闭
- **路径脱敏**：`/v2/models` 只暴露权重 basename
- **XSS**：多数动态值已转义；workbench 的 inline `onclick` 不能只依赖 HTML escape 保护 JavaScript 上下文，仍需消除内联事件或采用安全数据绑定
- **凭据**：`.env` / `.label-studio/.env` 权限 600；`.gitignore` 保留 `!.env.example`；新 Token 示例见 `.env.example`
- **监控真实性**：ML 后端 health 代码已增强；monitor 的 `/api/classifier` 能区分当前 83.67% 与历史 92.95%，但 `/api/live` 仍混用历史最佳

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

2026-08-04 二次复核按“代码已写入 / 自动化已覆盖 / 制品已重建 / 线上已加载”四层判定；完成本次文档纠偏后为 5 项基本关闭或已有主要运行/文档证据、14 项部分修复、5 项未关闭。未关闭项为 RA-002、RA-003、RA-008、RA-010、RA-024；逐项证据见 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md)。

当前回归证据仅能确认：`pytest tests -q` 22 通过、80 个 Python 文件 AST 通过、当前 bundle 16 个文件校验通过、recognize health 为 200。现有 22 项测试只覆盖命名、别名、不变性和 SKU 对齐，不覆盖 bundle/gold/unknown/hash/monitor/outbox/webhook/exporter/importer/背压等本轮核心整改，不能作为“24 项全部回归通过”的证据。

---

## 10. 关键文件索引

| 模块 | 文件 |
|---|---|
| 识别服务（级联引擎）| `src/recognize/service.py` |
| bundle 治理 | `src/models/bundle.py` |
| gold holdout | `src/data/gold_holdout.py` |
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

## 11. 已知坑

- torchvision 预训练权重下载易 hash 校验失败 → 删除损坏缓存重试
- YOLO.predict 不支持 bytes 输入 → 先转 numpy array
- pip 与 python 环境不一致 → 用 `python -m pip install`
- 图像裁剪须防越界（clamp）+ 等比缩放 + 拒识门禁兜底
- ultralytics fuse 警告（'Conv' object has no attribute 'bn'）为已知无害日志，不影响推理
- 修改 `src/recognize/service.py` 后必须重启 8091 服务才生效

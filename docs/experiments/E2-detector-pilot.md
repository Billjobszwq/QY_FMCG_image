# E2 detector pilot（Phase C）执行记录

- 手册依据：docs/superpowers/plans/2026-08-04-final-training-execution-gate.md Phase C
- 执行日期：2026-08-04
- Git commit（代码）：`abe2630`（G2-G6 门禁）+ train_v1 meta 时机修复（随本记录提交）
- 数据集：`e2_product_pilot_v1`（train 2000 / val 300，nc=1 "product"）
  - manifest_hash：`35f70f0a0cfd53b8`（4600 文件）
  - build_audit：`.datasets/e2_product_pilot_v1/build_audit.json`
  - 五键守卫：4 个 active 冻结集全部零交集（enforced=True，hits 全 0）
  - train/val 门店交集 0、session 交集 0
  - boxes：train 50,018 / val 7,975（registered 53,880 + unregistered 4,113，
    未注册框用 UNREGISTERED_BOX_FRAC=(0.07, 0.18) 近似，已披露）

## 共同超参（手册 Phase C）

imgsz=960，batch=4，device=mps（显式），seed=42，epochs=3，lr0=0.0005，
cls_weight=0.2，patience=3，close_mosaic=1，cos_lr=True，caffeinate -dimsu 包裹。

**与手册命令的两处记录在案偏差**：
1. 追加 `--optimizer AdamW`：Ultralytics `optimizer=auto` 会显式忽略 lr0
   （日志："ignoring 'lr0=0.0005'"，自动选 AdamW lr=0.002）。为让手册参数
   lr0=0.0005 生效，显式指定 AdamW。
2. train_v1 修复：不再在训练前预建 run 目录写 train_meta.json（否则
   Ultralytics exist_ok=False 发现目录已存在自动递增为 run_name-2，破坏
   唯一 run-name）；meta 改为训练完成后写入。第一次误启动产生的部分制品
   已归档至 `.models/archive/e2_p0_coco_s42*_failed_prestart_20260804`。

## E2-P0：yolo26m.pt（COCO 初始化）

- 命令：`caffeinate -dimsu python -m src.training.train_v1 --data-yaml .datasets/e2_product_pilot_v1/data.yaml --model yolo26m.pt --run-name e2_p0_coco_s42 --epochs 3 --imgsz 960 --batch 4 --device mps --seed 42 --lr0 0.0005 --cls-weight 0.2 --patience 3 --close-mosaic 1 --cos-lr --optimizer AdamW`
- 日志：`docs/experiments/logs/e2_p0_coco_s42.log`（device=mps 已确认）
- 耗时：2485s（0.682h；epoch ≈ 12.5/16.4/16.4 min，ep2 起吞吐下降与
  8091/8092 服务共存有关，无异常中断）
- MPS 内存：GPU_mem 10.4G → 11.6G → 峰值 12.6G 后稳定，无持续增长
- swap：训练前 13.70G → 训练中 13.67G，无增长
- Ultralytics val（best epoch 3）：P=0.386 R=0.617 mAP50=0.409 mAP50-95=0.218
- **严格 one-to-one IoU≥0.5 评估**（`.eval/e2/e2_p0_coco_s42/metrics.json`）：
  - recall@FP/image=3.0：**14.4%**
  - conf=0.25 定点：P=54.6% R=16.2% FP/photo=3.57
  - 吞吐 5.25 photos/s；延迟 p50=35.8ms p95=41ms（MPS，960）
  - conf=0.001 极限召回 97.5%（说明漏检主要来自置信度不足而非定位）

## E2-P1：best/sku_v4_best.pt（v4 初始化）

- 命令：同上，`--model best/sku_v4_best.pt --run-name e2_p1_v4_s42`
- 日志：`docs/experiments/logs/e2_p1_v4_s42.log`
- 迁移：Transferred 756/768（208 类头重建为 1 类）
- 初始 loss 明显低于 P0（box≈1.0 vs 1.6），预训练特征有效
- 耗时：2715.7s（0.754h；epoch 累计 916.9/1986.0/2677.5s）
- Ultralytics val（best epoch 2）：P=0.595 R=0.713 mAP50=0.690 mAP50-95=0.547
  （ep3 mAP50-95 回落 0.528，best=ep2）
- **严格 one-to-one IoU≥0.5 评估**（`.eval/e2/e2_p1_v4_s42/metrics.json`，pilot val 300 张）：
  - recall@FP/image=3.0：**39.0%**
  - conf=0.25 定点：P=59.7% R=71.6% FP/photo=12.83
  - 吞吐 6.75 photos/s（MPS，960）

## dev_v2 协议集同口径评估（801 张，GT=锚点合成盒，已披露）

| 权重 | recall@FP3.0 | conf=0.25 P | conf=0.25 R | FP/photo | 吞吐 | p95 |
|---|---|---|---|---|---|---|
| E0 生产 v4（基线） | **20.88%** | 66.8% | 18.4% | 2.33 | 8.59/s | 38.9ms |
| P0（COCO 3ep） | 13.51% | 53.4% | 13.1% | 2.90 | 7.47/s | 37.2ms |
| P1（v4 初始化 3ep） | **24.23%** | 61.6% | 33.4% | 5.28 | 7.88/s | 35.6ms |

评估产物：`.eval/e2/e0_prod_v4_on_dev_v2/`、`.eval/e2/e2_p0_coco_s42_on_dev_v2/`、
`.eval/e2/e2_p1_v4_s42_on_dev_v2/`；日志见 `docs/experiments/logs/*_on_dev_v2_eval.log`。
注：dev_v2 为新门店新场景，绝对召回整体低于 pilot val（分布外），但三权重同口径可比。

## 晋级判定（Phase D）：**不晋级，停止全量训练**

手册晋级门槛逐项核对（胜出方案 = P1，v4 初始化）：

| 门槛 | 要求 | 实测 | 判定 |
|---|---|---|---|
| recall@既定FP/image | 相对 E0 提升 ≥10pp | 24.23% vs 20.88%，**+3.35pp** | ✗ 未达标 |
| FP/image | ≤ 基线 1.2 倍 | conf=0.25：5.28 vs 2.33×1.2=2.80 | ✗ 未达标 |
| 训练稳定性 | 无 NaN/CPU 回退/内存泄漏 | device=mps 全程，无异常 | ✓ |

结论：两 pilot 均完整，但胜出方案 P1 未达到晋级门槛（+3.35pp < +10pp 且
FP/image 超标）。按手册第五节规则，**不自动继续全量 10 epoch 训练**，
不启动 classifier 阶段，不发布任何新 bundle。生产 bundle
`prod_20260804_v4_r2` 保持不变。

后续改进方向（需人工决策后启动，非本轮自动执行）：
- P1 仅 3 epoch（lr 尚在 warmup 尾段），更长训练/更大 pilot 可能提升，但晋级门槛未达即停止是手册硬规则；
- dev_v2 GT 为锚点合成盒（非人工框），绝对指标偏低含口径因素，已在各报告披露；
- 若业务认为 +3.35pp 方向正确，需显式授权放宽门槛或修订协议后重启。

## 评估口径（G5）

- 严格 one-to-one IoU：pred 按 conf 降序贪心，每个 GT 至多匹配一个 pred
- GT 来自数据集 labels（锚点+SKU 比例盒生成的合成框，与训练标签同源）
- recall@固定FP/image：PR 扫描（conf 从高到低累计）线性插值到 FP/photo=3.0
- E0 基线对照口径见 docs/experiments/E0-current-bundle-baseline.md 与
  e0_strict_iou（business accepted precision 含 fp_accepted 分母）

## 晋级判定（Phase D 前置）

两 pilot 均完成后对照手册晋级门槛（已判定：不晋级，见上节）：
- recall@既定FP/image 提升 ≥10pp（相对 E0 detector 覆盖基线）
- FP/image ≤ 基线 1.2 倍
- 无 NaN/Inf、无 CPU 回退、无内存持续增长、无 swap 恶化

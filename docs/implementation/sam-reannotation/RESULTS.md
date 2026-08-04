# SAM 辅助重标注专项 · 结果

（本文件在各 Gate/实验产出后追加；最终按手册§十六格式交付。）

## Gate 结果汇总

| Gate | 结果 | 关键指标 | 证据 |
|---|---|---|---|
| 预检基线 | PASS | 74 tests passed；bundle verify ok（16 文件） | EXECUTION-LOG.md |
| S0 SAM 准入 | **PASS（选 sam2.1_hiera_small）** | 5张 smoke ✅；50张/990点 ✅；MPS 实跑、确定性 True、无 swap 增长、无内存泄漏 | `.sam_runs/smoke_*`、`.sam_runs/bench_*` |
| Q0 质量过滤 | 待执行 | — | — |
| S1 SAM 标注质量 | 待执行 | — | — |
| D0 数据集门禁 | 待执行 | — | — |
| E3 pilot | 待执行 | — | — |

## Gate S0 双模型对比（2026-08-04，M3 Max MPS，隔离 venv）

| 指标 | hiera_small | hiera_base_plus |
|---|---|---|
| 5张 smoke（92点）wall | 10.9s | 7.8s |
| 50张/990点 wall | 199.8s | 204.2s |
| encoder 平均 | 0.100s | 0.189s |
| decoder/点 平均 | 0.019s | 0.020s |
| MPS peak | 2372MB | 4067MB |
| RSS | 3888MB | 3658MB |
| 确定性重跑 | True | True |
| swap 前后 | 无增长 | 无增长 |
| 真实点硬约束通过率（代理） | 11/170 (6.5%) | 2/170 (1.2%) |

决策（手册§五：选满足质量要求的最小模型）：**sam2.1_hiera_small**。
理由：两模型均 MPS 稳定/确定/无泄漏；Small 更快、内存减半、真实点通过率更高。

注：硬约束通过率偏低为保守设计预期（触碰粗 ROI 边界/多连通域→降级人工，手册§六.6）；
网格点落在非商品区属 benchmark 点源限制，质量终判由 S1 人工框承担。
阈值校准须用独立校准集（禁用 diagnostic_v1）。

## 真实框统一评估（diagnostic_v1，E0/P0/P1）

待真实框完成后填写：IoU 0.50/0.75、recall@FP1/3/5、FP/photo、逐实例 10 类错误账本。

## 晋级判定

待 E3 pilot 后按 D-010 判据填写。

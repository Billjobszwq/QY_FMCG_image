# SAM 辅助重标注专项 · 执行日志

格式：时间 | 命令/动作 | 退出码 | 耗时 | 关键输出 | 制品路径。

## 2026-08-01 基线核对

| # | 命令 | 结果 |
|---|---|---|
| 1 | `git status --short` | 仅 `?? .superpowers/`（保留不清理） |
| 2 | `git rev-parse HEAD` | `3f559911f95d0e9d7215a031d1cd79cd649b6b80`（main，ahead origin/main 11） |
| 3 | `git branch -vv` | 仅 main；后新建 `feat/sam-reannotation` |
| 4 | `python -m pytest -p no:cacheprovider -q` | **74 passed**（2.42s）✅ 与预期一致 |
| 5 | `python -m src.models.bundle verify --bundle-id prod_20260804_v4_r2` | `{"ok": true, "n_files": 16}` ✅ 与预期一致 |

- Python：`/Users/zhangweiqi/miniconda3/bin/python`（3.13.2，arm64）
- 数据基线：e2_product_pilot_v1 build_audit（train 2000/50018 框，val 300/7975 框，manifest_hash=35f70f0a0cfd53b8，五键守卫全 0，git=abe2630）
- 无训练进程运行；生产服务 bundle 未动。

## 2026-08-04 隔离环境 / SAM 契约 / checkpoint / 质量流水线

| # | 动作 | 结果 |
|---|---|---|
| 1 | `.venv_sam` 创建（Python 3.13.2） | torch 2.13.0 / torchvision 0.28.0 / SAM-2 1.0 / numpy 2.5.1 / opencv-headless 5.0.0.93；`torch.backends.mps.is_built/available=True` ✅ |
| 2 | SAM 契约 TDD（prompts/candidates/evidence/prediction/provenance） | 40 个新测试 → 实现 → **commit bcd7576** |
| 3 | runtime + worker 子进程隔离（MPS 门禁 fail-closed） | +5 测试 → **commit a0f8b5d**，119 passed |
| 4 | checkpoint 下载 `scripts/download_sam_ckpts.py` | 退出码 0，见下 SHA 表 |
| 5 | 四级质量策略 TDD（policy/analyzers/evidence/runner） | +18 测试 → 全量 **137 passed**（2.56s）✅ |
| 6 | Gate S0：5 张 smoke + 50 张/990 点 benchmark（双模型） | MPS 无 fallback、确定性✅、无内存泄漏；选 hiera_small → **commit 04f2c30** |
| 7 | LS 导入 TDD（仅 prediction）+ 离线 payload | +4 测试，141 passed → **commit 6e862a9**；LS 离线见 SAM-002 |
| 8 | 质量批量 120 张 + 两轮校准（moire qa_v2 / blur qa_v3） | accept 92 / manual_review 28 / reject 0 → **commit 892624d** |
| 9 | 人工双审队列 TDD + 生成 250 项 pending 队列 | +10 测试；`.review_queue/review_queue_diag_v1.json`；status=awaiting_human_review |
| 10 | 真实框统一评估器（one-to-one，IoU .50/.75，recall@FP1/3/5，10 类账本） | +8 测试；驱动 `scripts/run_truebox_eval.py`（待真实框完成后重评 E0/P0/P1） |
| 11 | e3 truebox builder + 守卫契约（test_truebox_dataset_guard） | +11 测试；全量 **170 passed**；fail-closed：审核100%/五键/门店session隔离/绝不覆盖 |

### SAM 2.1 checkpoint 证据（.sam_checkpoints/manifest.json）

| 模型 | 字节数 | SHA256 | 许可证 |
|---|---|---|---|
| sam2.1_hiera_small | 184,416,285 | `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38` | Apache-2.0 |
| sam2.1_hiera_base_plus | 323,606,802 | `a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5` | Apache-2.0 |

下载源：`https://dl.fbaipublicfiles.com/segment_anything_2/092824/`（facebookresearch/sam2）。

## 待执行（按 PLAN 顺序）

- [x] SAM venv 创建与依赖安装（记录 pip freeze 摘要与 torch 版本）
- [x] checkpoint 下载（URL/SHA256/许可证记录后执行）
- [x] 5 张 smoke（MPS，记录设备/encoder/decoder/RSS/MPS 内存/swap）
- [x] 50 张 / ~1000 点 benchmark（hiera_small vs base_plus）
- [ ] **人工双审 200 张 + 盲抽 50 张**（awaiting_human_review，不伪造）
- [ ] 导出 diagnostic_v1_truebox_v1（不改原协议文件）
- [ ] 统一重评 E0/P0/P1（scripts/run_truebox_eval.py）
- [ ] Gate D0 → e3 builder → 3ep pilot（逐级门禁）

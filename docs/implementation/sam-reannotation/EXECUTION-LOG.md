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

## 待执行（按 PLAN 顺序）

- [ ] SAM venv 创建与依赖安装（记录 pip freeze 摘要与 torch 版本）
- [ ] checkpoint 下载（URL/SHA256/许可证记录后执行）
- [ ] 5 张 smoke（MPS，记录设备/encoder/decoder/RSS/MPS 内存/swap）
- [ ] 50 张 / ~1000 点 benchmark（hiera_small vs base_plus）

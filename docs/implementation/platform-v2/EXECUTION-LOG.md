# Platform V2 — EXECUTION-LOG

> 记录规则：每个命令的命令体、退出码、耗时、结果、制品路径。时间 = 本机 Asia/Shanghai。

## M0 基线盘点（分支创建前，feat/sam-reannotation @ c9998af）

| # | 命令 | 退出码 | 结果摘要 |
|---|---|---|---|
| 1 | `git status --short` / `git rev-parse HEAD` / `git log --oneline -8` | 0 | 分支 feat/sam-reannotation @ c9998af；工作树：M docs/README.md、M full-project-execution-program.md（用户的新手册索引切换，保留）；?? 新手册文件；?? .quality/ .sam_checkpoints/ .sam_runs/ .superpowers/（不暂存不清理） |
| 2 | 端口探测 `curl -m3` × 8091/8092/8300/8301/8304/8400/8455 | 0 | 8091=404(/)、8092=200、8300=000、8301=000、8304=000、8400=000、8455=404(/) |
| 3 | `curl http://127.0.0.1:8091/v2/health` | 0 | ok=true，cascade_v3，bundle prod_20260804_v4_r2，n_classes=208 |
| 4 | `curl http://127.0.0.1:8092/api/live` | 0 | 返回训练监控 JSON（resnet18 ep80 历史缓存视图） |
| 5 | `python -m pytest -p no:cacheprovider -q` | 0 | **170 passed in 2.91s**（Python 3.13.2，/Users/zhangweiqi/miniconda3/bin/python3） |
| 6 | `verify_bundle('prod_20260804_v4_r2')`（src.models.bundle） | 0 | ok=true，n_files=16 |
| 7 | warehouse 只读计数（`mode=ro` URI） | 0 | 12 表：annotation=170、asset=9、sku_catalog=28、recognition_run=22、model_bundle=1、model_version=3、review_event=5、webhook_event=1、audit_outbox=0、auto_label=0、dataset_version=0 |
| 8 | `du -sh` 制品目录 | 0 | .models 2.9G、.training_data 3.0G、.eval 356M、.sam_checkpoints 484M、.sam_runs 417M、.quality 428K、.review_queue 84K、.warehouse 152K |
| 9 | 必读文件通读 | — | 新手册 622 行、L0 架构 1759 行、CODEX-PROJECT-HANDBOOK 559 行、git-version-control 475 行、training-history、services.json、SAM STATUS/DECISIONS 全部读完 |
| 10 | `git checkout -b feat/usable-platform-foundation` | 0 | 新分支基于 c9998afef5bdda3fdcfea3db5a82892f0be08536；工作树改动随分支保留 |

## M0 提交记录

（待填：暂存文件清单 → 提交哈希）

## M1 / W1–W3

（待填）

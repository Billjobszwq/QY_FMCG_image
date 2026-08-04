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

- 暂存 9 个文档文件（README.md、program.md、新手册、platform-v2 六文档），`git diff --cached --name-only` 核对无制品 → 提交 **f91c0e6**（9 files, +866/-2）

## M1 / W1–W4

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | `pytest tests/platform/test_health_aggregation.py`（W1+W2 TDD） | 0 | <1s | 15 测试全绿；修复点：aggregate 测试需构造 ServiceStatus 而非裸字符串；omlx 探测 `/` 404 → 改 `/health`（200 {"status":"healthy"}，无需 key） |
| 2 | `python3 -m src.platform.api.run --port 8400`（后台真实启动） | 0 | 持续 | `/api/v1/health` 返回 degraded（8300/8301 DOWN 非关键 → degraded；8091/8092/8455 healthy）；日志 /tmp/platform_8400.log |
| 3 | W1+W2 提交 | 0 | — | **97020d6**（src/platform 骨架 + health 聚合 + 15 测试） |
| 4 | `pytest tests/platform/test_legacy_adapters.py`（W4 TDD） | 0 | <1s | 28 测试全绿；修复点：错误需返回 JSON `{"error": kind}`（HTTPException 无 error 字段） |
| 5 | 真实识别 E2E（curl 8400 bridge） | 0 | ~0.5s | 上传 `.training_data/images/train/36619578.jpg` → count=2（罐装雪碧330ml conf 1.0、2L七喜 0.644）；照片1106/190.jpg 与 百事&可口 均 0 检出，直连 8091 同样 0 → 确认是上游 fail-closed 业务行为非 bridge bug |
| 6 | W4 提交 | 0 | — | **54cac63**（legacy.recognition.v2 + legacy.training.monitor adapters + bridge 端点 + 28 测试） |
| 7 | `npm install`（W3，web/） | 0 | ~20s | 69 包；许可证核查：react/react-dom/react-router-dom/vite MIT，typescript Apache-2.0，全部可接受 |
| 8 | `npx tsc -b && npx vite build` | 0 | build 366ms | dist 产物 web/dist/（gitignore）；React 18.3.1 + react-router-dom 6.26.2（HashRouter）+ Vite 5.4.8 + TS 5.5.4 |
| 9 | 浏览器 E2E（Chrome headless，browser-use MCP transport 损坏降级方案） | 0 | ~6s/页 | 6 张截图：/tmp/pv2_evidence/m1_{overview,recognition,training,status,runs,annotation}.png；overview 显示 degraded 横幅+真实服务表；training 显示 8092 真实数据（resnet18 ep80/80、best acc 83.67%、YOLO runs v1–v6） |
| 10 | W3 提交 | 0 | — | **2d9a4ef**（17 files, +2465；.gitignore 补 web/node_modules/、web/dist/） |
| 11 | M1 验收回归 `pytest -q` 全量 | 0 | 2.97s（总 4.4s） | **198 passed**（基线 170 + 平台 28） |
| 12 | M1 验收后 8091/8092 复查 | 0 | — | 8091 /v2/health ok=true（bundle prod_20260804_v4_r2 未动）；8092 /api/live 正常；8400 /api/v1/health 200 |

## M1 验收结论

- 八项验收全过（见 ACCEPTANCE.md M1 矩阵）→ **M1 DONE**

## M2 / W5–W6

| # | 命令 | 退出码 | 耗时 | 结果摘要 |
|---|---|---|---|---|
| 1 | `pytest tests/platform/test_platform_store.py`（W5 TDD） | 0 | 0.18s | 20 测试全绿（migration 幂等+防篡改、Run/Node/Checkpoint/Job/Attempt/Audit/Usage/Evidence/Asset、备份 integrity_check、重启恢复） |
| 2 | W5 提交 | 0 | — | **46d2f25**；.gitignore 补 `.platform/`；全量 218 passed |
| 3 | `pytest tests/platform/test_m2_contracts.py tests/platform/test_m2_registry.py`（W6 TDD） | 0 | 0.28s | 25 测试全绿（契约 extra=forbid、IAM 双审批分离、Registry 重复/缺 adapter 拒绝、Job 状态机、RequestContext、依赖方向守卫） |
| 4 | 8400 重启 + `curl /api/v1/capabilities` | 0 | ~3s | 返回 2 个 legacy capability；`X-Request-Id` 响应头存在；health 200 degraded |
| 5 | `npx tsc -b && npx vite build` | 0 | 2.27s | 系统状态页新增 Capability 表；Chrome headless 截图 /tmp/pv2_evidence/m2_status.png（真实渲染） |
| 6 | 全量回归 `pytest -q` | 0 | 3.17s | **243 passed** |
| 7 | W6 提交 | 0 | — | **1dc4cc8**（10 files） |

## M2 验收结论

- Registry/契约/Adapters/存储 四项全过（见 ACCEPTANCE.md M2 矩阵）→ **M2 DONE**

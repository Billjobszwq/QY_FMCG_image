# 启动方式 / 运行手册

> 前提：已按 `docs/setup.md` 装好依赖、起好 omlx、配好 `.env`。所有命令在项目根目录执行。
>
> **ISSUE-018：当前受支持架构为级联链路（:8300/:8301/:8304/:8091/:8092），唯一服务清单见
> [`docs/services.json`](./services.json)。下文 TL;DR 与 8090/8091 旧链路为 `legacy`，
> 只用于历史回归验证，禁止生产使用；新成员请直接按“当前核心命令”小节启动。**

## 全流程 TL;DR（legacy：早期 smoke 链路，只用于历史回归，禁止生产）

```bash
python -m src.catalog.build_kb          # 1 建知识库      → .kb
python -m src.field.photos              # 2 入库实景      → .field
python -c "from src.data import warehouse as w; c=w.connect(); w.migrate(c)"  # 3 初始化仓库
python -m src.labeling.runner --mode B --max-photos 9     # 4 自动提案
python -m src.labeling.review_server --port 8090          # 5 人工审核（浏览器打开 :8090，逐张 approved）
python -m src.eval.label_eval           # 6 标注质量评测
python -m src.training.dataset          # 7 构数据集      → .datasets/v1
python -m src.training.trainer          # 8 smoke 训练    → .models + model_version
python -m src.recognize.api --port 8091 # 9 起识别接口
python -m src.eval.recog_eval           # 10 识别质量评测
```

## 逐步说明

**1 建知识库** — 读 `搭建初期P1/`，内容哈希去重，VLM 出结构化卡，Qwen3 出 1024d 向量，标记促销图/缺参考。产物 `.kb/`。

**2 入库实景** — 解析 `实景照片.xlsx`（只读），把 `.aspx` 解成 OSS 直链下载，写 `.field/manifest.json` + blobs。它模的 `x,y,name` 作金标/种子。

**3 初始化仓库** — 在 `.warehouse/db.sqlite` 建 8 表 + 追加触发器；幂等，可重复执行。

**4 自动提案（标注阶段）** — 模式 B 用它模种子画框+打 SKU+复核纠错；**只写 `proposals/`，不写训练源**；每张入 `review_queue.json`（按不确定度排序）。`--max-photos` 控制范围与成本。

**5 人工审核（人工门）** — 打开 http://127.0.0.1:8090 ：看图+提案框，确认/改 SKU/加框/删框，设照片状态 `approved/rework/rejected`，提交。
- 仅 `approved` 的照片生成 `.labels/approved/<id>.txt`（训练源）；`rework/rejected` 会移除已生成的训练源。
- 每次提交追加 `review_events.jsonl`（含 before/after）。
- 快捷："一键全确认" 用于模型提案质量好的照片。
- 无人值守的闭环验证：`python scripts/label_proof.py`（程序化模拟一次人工通过，证明 提案→人审→approved 链路）。

**6 标注质量评测** — 提案 vs 金标：覆盖率、标签一致率、**大模型 vs 它模 不一致数**（=复核队列+它模错标挖掘）。报告 `.labels/label_eval.json`。

**7 构数据集** — 仅读 `approved/` → YOLO 格式，**按照片切分**防泄漏；不足 2 张时 val=train（smoke）。产物 `.datasets/v1/data.yaml`。

**8 smoke 训练** — ultralytics 从 yolo11n 微调 1 epoch（CPU 可跑，证明链路）；在仓库登记 `model_version`（code_hash/data_version/指标/权重哈希，状态 draft）。**真实训练**需更多 approved 照片 + 更多 epoch + GPU。

**9 起识别接口** — stdlib HTTP :8091。
```bash
# 用实景某张图识别（asset_id 取自 manifest）
curl -s -X POST http://127.0.0.1:8091/v1/recognize -H 'Content-Type: application/json' \
  -d '{"asset_id":"34571762"}'
# 或传 base64：{"image_base64":"...."}
curl -s http://127.0.0.1:8091/v1/health
```
检测用通用瓶身检测器，识别用知识库+VLM；每次调用追加 `recognition_run` 审计。

**10 识别质量评测** — 通用检测+KB识别 vs 金标：检测召回、识别准确（在检出的框上）。报告 `.labels/recog_eval.json`。

## 起两个本地服务（常驻）【legacy：只用于历史回归，生产请用下方“当前核心命令”】

```bash
python -m src.labeling.review_server --port 8090   # 人工审核（legacy，生产走 Label Studio :8300）
python -m src.recognize.api        --port 8091   # 识别接口（legacy /v1，生产走级联 src.recognize.service /v2）
```

> 二者均无额外依赖；要后台常驻可加 `nohup ... &` 或纳入你的进程管理。

## 监控服务（:8092）— 看门狗守护方案

监控服务可由**看门狗**每 10 秒探活并自动拉起。该机制降低进程退出风险，但不能保证“永不挂”；仍需监控看门狗本身、端口、RSS 和日志。**不要同时用多个入口重复拉起 monitor**：

```bash
# 启动看门狗（会自动拉起井守护监控）
nohup bash scripts/monitor_watchdog.sh >/dev/null 2>&1 & disown

# 查看看门狗状态 / 日志
ps aux | grep [m]onitor_watchdog
tail .models/monitor_watchdog.log
```

> 背景：监控进程直接 nohup 起会被会话回收反复挂；launchd 因项目在 `~/Documents`（macOS TCC 隐私保护）无权限不可用。看门狗跑在有权限的用户态，可靠守护。监控实时数据来自 `/api/live`（动态检测当前活跃训练：YOLO 训练解析日志、分类器读 live_progress）。

## 新版前端（:4173）— 静态 dist + 同源 /api 代理

新版产品前端（PostHog 风格桌面式 UI，v3 真实数据，见 `frontend/README.md`）由零依赖的
`frontend/server/serve.mjs` 服务：`dist/` 静态产物 + `/api/*` 反向代理到平台后端
`127.0.0.1:8400`（同源，保留 cookie / 头部）。无守护需求（静态服务，挂了重起即可）：

```bash
# 首次：安装依赖并构建
npm --prefix frontend install
npm --prefix frontend run build

# 启动（正式端口 4173，与 docs/services.json 的 frontend 条目一致）
nohup node frontend/server/serve.mjs --port 4173 >.models/frontend_serve.log 2>&1 & disown

# 探活（GET / 与 /health 均返回 200）
curl -sf http://127.0.0.1:4173/ >/dev/null && echo frontend_ok
```

> 开发模式用 `npm --prefix frontend run dev`（:5173，Vite 同源代理，仅调试，不登记服务清单）。既有业务工作台 `web/` 不受影响。

## 测试

```bash
python -m pytest tests/unit tests/contract -q     # 不变性/对齐/命名/别名 等契约
```

## 故障排查

| 现象 | 处理 |
|---|---|
| VLM/OCR/嵌入全报错 | omlx 未起或模型未加载；跑 setup 第 5 节校验 |
| `REFUSE WRITE into read-only source` | 正常——你在试图写只读原始资产，别写 |
| 实景入库 OSS 失败 | 确认能访问 `bucket-spar.oss-cn-shanghai.aliyuncs.com` |
| `docker compose up` 拉镜像超时 | 配国内镜像源（setup 第 6 节）或 pre-pull+retag；或干脆用原生路径 |
| 训练 `no images/labels` | `approved/` 为空——先在第 5 步 approved 至少一张 |
| 识别接口检测不到瓶 | 通用检测器对密集小瓶召回有限；属已知，训练饮料专用检测器后改善 |

## 当前状态与待办

> 完整当前状态快照见 [`handbook.md`](./handbook.md)，严格二次复核见 [`latest-handbook-reverification-2026-08-04.md`](./latest-handbook-reverification-2026-08-04.md)。本 runbook 的 TL;DR 为早期 smoke 链路，实际已演进到级联架构。

- ✅ 平台建成：Label Studio 标注/审核（:8300）、ML 后端自动标注（:8301）、编排 API（:8304）、识别 dashboard、统一监控（:8092）。
- ✅ YOLO 检测器冻结于 sku_v4（mAP50=0.6887）作画框器。
- ⏹️ 级联分类器当前训练已停止；生产 checkpoint 为 208 类 ResNet18，记录 val_acc 83.67% @ ep10，不含 `__unknown__`。
- ⚠️ 2026-08-04 复核时实际监听的只有 8091 recognize 和 8092 monitor；8300、8301、8304 未运行，不能把“代码存在”写成“在线联调完成”。
- ⏳ 下一步不是直接续训：先从未训练新门店冻结 gold-v2，跑检测真实框上限和 GT-crop classifier oracle，再按 [`后续训练方案`](./superpowers/plans/2026-08-04-model-training-next-phase.md) 决定 detector、裁剪数据或 classifier 路线。

**当前只读验证命令**（详见 handbook.md；端口/命令以 [`docs/services.json`](./services.json) 为准）：
```bash
python -m src.models.bundle current
python -m src.models.bundle verify --bundle-id prod_20260804_v4_r2
curl -s http://127.0.0.1:8091/v2/health
python -m pytest tests/ -q
```

> 训练、数据重建、发布和服务重启都是写操作，不属于只读复核。执行前应先取得负责人确认并创建不可变数据/实验版本。

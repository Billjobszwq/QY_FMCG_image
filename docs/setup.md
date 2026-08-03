# 环境与项目部署

> 本系统**默认以"本机原生"方式运行，不依赖 Docker**。Docker / Postgres / MinIO / Label Studio 均为**可选**，用于日后多节点/协作/生产形态。下面先给原生路径，再给可选项。

## 0. 形态说明

| 组件 | 原生（默认，今天就能跑） | 可选升级 |
|---|---|---|
| 元数据库 | SQLite（`.warehouse/db.sqlite`） | Postgres（schema 同构，`migrations/001_schema.sql`） |
| 向量 | numpy 余弦（`.kb/vectors.npy`） | pgvector / sqlite-vec |
| 对象存储 | 本地内容寻址（`.kb/.field/.../blobs`） | MinIO / 阿里 OSS |
| 队列 | 无（同步/后台脚本） | Redis / PG `SKIP LOCKED` |
| 人工审核 UI | 自建零依赖 `review_server`（:8090） | Label Studio（`pip install`，同契约） |
| 模型服务 | omlx（本机，必需） | — |

## 1. 系统要求

- Python **3.11–3.13**（已在 3.13 验证）。
- 磁盘：参考图 + 实景缓存 + 模型权重，预留数 GB；百万级实景按需扩。
- 算力：标注/识别用 omlx（CPU 或 GPU 皆可，取决于你 omlx 的部署）；YOLO 训练建议 GPU，**smoke 训练 CPU 即可**。
- 网络：omlx 走 `127.0.0.1`，**无需外网**；实景源图来自阿里 OSS（入库时需可达）。

## 2. 安装 Python 依赖

```bash
pip install openai httpx pillow numpy openpyxl ultralytics
```

> `ultralytics` 会带入 `torch`。无需单独装 docker 相关包。

## 3. 启动 omlx 模型服务（必需）

系统所有"看/读/嵌入"都走本地 omlx 的 OpenAI 兼容接口。需你先启动 omlx 并加载以下模型：

| 用途 | 模型 id | 配置项 |
|---|---|---|
| 视觉裁决/抽取 | `gemma-4-31b-it-4bit` | `OMLX_VLM_MODEL` |
| 文本嵌入 | `Qwen3-Embedding-0.6B-8bit` | `OMLX_EMBED_MODEL` |
| OCR（带词框） | `PaddleOCR-VL-1.5-6bit` | `OMLX_OCR_BOX_MODEL` |
| OCR（纯文本） | `DeepSeek-OCR-2-4bit` | `OMLX_OCR_TEXT_MODEL` |

默认端点 `http://127.0.0.1:8455/v1`（`OMLX_BASE_URL`）。

## 4. 配置 `.env`

```bash
cp .env.example .env
```

关键项（原生路径只需 omlx 相关；其余为可选项默认值）：

```dotenv
OMLX_BASE_URL=http://127.0.0.1:8455/v1
OMLX_API_KEY=1234                 # 本地 omlx 访问键；仅经 .env 注入，禁止写进代码
OMLX_VLM_MODEL=gemma-4-31b-it-4bit
OMLX_EMBED_MODEL=Qwen3-Embedding-0.6B-8bit
OMLX_OCR_BOX_MODEL=PaddleOCR-VL-1.5-6bit
OMLX_OCR_TEXT_MODEL=DeepSeek-OCR-2-4bit
KB_REFERENCE_DIR=搭建初期P1        # 参考图目录（只读）
FIELD_XLSX=实景照片.xlsx           # 实景清单（只读）
KB_DATA_DIR=.kb
```

> `POSTGRES_* / REDIS_* / MINIO_* / LABEL_STUDIO_*` 仅在启用第 6/7 节可选项时使用，原生路径忽略。

## 5. 校验环境（一键）

```bash
# omlx 是否可达 + 模型是否齐全
curl -s "$OMLX_BASE_URL/models" -H "Authorization: Bearer $OMLX_API_KEY" | head -c 600
# 依赖是否可导入
python -c "import openai,httpx,PIL,numpy,openpyxl,ultralytics; print('deps ok')"
```

## 6.（可选）Docker 基础设施

仅当你需要 Postgres/MinIO/Redis/Label Studio 容器时。**国内直连 Docker Hub 常 TLS 超时**，先给 Docker Desktop 配镜像源（Settings → Docker Engine）：

```json
{ "registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.1ms.run"] }
```

Apply & Restart 后：

```bash
docker compose up -d          # 拉起 postgres+pgvector / redis / minio / label-studio
docker compose ps             # 四个均 healthy 即成功
```

> 镜像源仍拉不到时，可用 `pre-pull + retag`：`docker pull <mirror>/pgvector/pgvector:pg16 && docker tag <mirror>/pgvector/pgvector:pg16 pgvector/pgvector:pg16`，对其余镜像同理。
> 不启用本节也完全不影响原生路径——SQLite/本地 fs/自建审核已覆盖全部功能。

## 7.（可选）Label Studio（原生，无需 docker）

自建 `review_server` 已能满足单人/小规模审核。需多人协作/企业功能时：

```bash
pip install label-studio
label-studio start             # 新建项目时粘贴 configs/label-studio/label_config.xml
```

> 它与自建审核服务**共用同一数据契约**（`review_event` / `approved`），切换不改数据模型。

## 8. 常见坑

- **omlx 未起 / 模型未加载** → 所有 VLM/OCR/嵌入调用报错；先跑第 5 节校验。
- **`OMLX_API_KEY` 写进代码** → 违反红线；只放 `.env`。
- **实景入库报 OSS 错** → `.xlsx` 里的 URL 是 `.aspx` 查看页，代码已自动解析为真实 OSS 直链；若仍失败，确认本机能访问 `bucket-spar.oss-cn-shanghai.aliyuncs.com`。
- **想"修改原始数据"** → 禁止。`搭建初期P1/`、`实景照片.xlsx`、`.field/blobs` 在代码层被 `paths.assert_writable` 拦为只读。

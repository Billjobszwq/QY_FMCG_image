# 项目结构与数据布局

## 1. 三阶段模型与数据流

```
[参考图 搭建初期P1/]  [实景 实景照片.xlsx + OSS]      ← 只读原始资产
        │                       │
        ▼                       ▼
   建知识库 .kb            入库 .field (manifest+blobs)
 (向量+别名+清洗)         (它模给的 x,y,name 作金标/种子)
        │                       │
        └──────────┬────────────┘
                   ▼
        ┌──────────────────────┐   标注阶段（大模型=老师）
        │ labeling 双模式       │   模式B: 种子→画框→打SKU→复核/纠错
        │  → 提案 proposals/    │   模式A: 从零定位+识别
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐   人工门（每张图）
        │ review_server :8090   │   通过→ approved/  ；否→ 不入库
        │  (或 Label Studio)    │   人工动作→ review_events.jsonl(追加)
        └──────────┬───────────┘
                   ▼ approved（训练唯一来源）
        ┌──────────────────────┐   训练阶段（YOLO=学生）
        │ training: dataset→train│   登记 model_version
        └──────────┬───────────┘
                   ▼ 训好的权重
        ┌──────────────────────┐   识别阶段（热路径）
        │ recognize :8091       │   通用检测瓶身 + 知识库/VLM 识别SKU
        └──────────────────────┘   审计→ recognition_run(追加)
```

**裁决原则**：检索只**召回** top-K，最终裁决 = **属性硬过滤 + VLM 终审**（不取 embedding top1）。
**人工门**：自动产出**只是提案**，张张过人工才进 `approved/`；低置信进复核队列、**不训练**。

## 2. 源码结构 `src/`

```
src/
├── common/        基础设施
│   ├── config.py      配置（仅从 .env 读密钥）
│   ├── hashing.py     内容哈希（去重/不可变引用）
│   ├── omlx.py        omlx 客户端：embed / vlm_extract / vlm_classify / ocr_text / ocr_boxes
│   ├── oss_urls.py    实景 .aspx → OSS 直链
│   └── paths.py       不变护栏：assert_writable / safe_write_*（原始资产只读）
├── catalog/       知识库
│   ├── naming.py      名称解析 + 归一匹配键
│   ├── alias_registry.py  canonical 注册表（两套命名+错字+kb_missing）
│   ├── ingest.py      参考图遍历/骨架
│   ├── store.py       向量库（本地 numpy，余弦检索）
│   └── build_kb.py    建库：入库+VLM卡+向量+清洗标记
├── field/         实景入库
│   └── photos.py      解析 xlsx + 下 OSS + manifest（read_only 打开 xlsx）
├── data/          数据仓库层
│   └── warehouse.py   SQLite 实现，读 migrations/001_schema.sql，追加式 API
├── labeling/      标注阶段（大模型）+ 人工门
│   ├── localize.py    定位：种子外扩 / OCR 锚（不依赖训好的 YOLO）
│   ├── assign.py      SKU 裁决：检索召回→硬过滤→VLM 终审（双模式）
│   ├── emit.py        写 proposals / reviews / approved / events（三者分离）
│   ├── runner.py      编排：自动只产提案 + 每张入复核队列
│   ├── review_server.py  零依赖人工审核服务 :8090
│   └── review.html    审核页面（画框/改SKU/确认/照片状态）
├── eval/          评测
│   ├── label_eval.py  标注质量：提案 vs 金标 + 大模型vs它模 不一致挖掘
│   └── recog_eval.py  识别质量：通用检测+KB识别 vs 金标
├── training/      训练阶段
│   ├── dataset.py     approved → YOLO 格式（按照片防泄漏切分）
│   └── trainer.py     ultralytics 微调 + 登记 model_version
├── recognize/     识别阶段
│   └── api.py         检测瓶身 + KB/VLM 识别 + stdlib 接口 :8091 + 审计
└── pipeline/      早期识别评测骨架（autolabel/recognize，待归位 eval）
```

## 3. 根目录文件

```
compose.yaml              可选 docker 编排
.env / .env.example       配置 / 模板（密钥只在此）
conftest.py               测试路径
migrations/001_schema.sql 数据仓库 schema（SQLite 与 PG 同构）
configs/label-studio/label_config.xml   可选 LS 标注配置
data/sku_aliases.json     别名注册表数据（跨命名法+错字+kb_missing）
scripts/label_proof.py    闭环一键验证（提案→模拟人审→approved）
搭建初期P1/               参考图（只读）
实景照片.xlsx             实景清单（只读）
```

## 4. 运行时数据目录

```
.kb/            知识库：skus.json, vectors.npy, vector_ids.json, blobs/<aa>/<sha>
.field/         实景：manifest.json, blobs/<aa>/<sha>
.labels/        标注产物：
   proposals/<id>.txt|.json   自动提案（预标注，非训练源）
   reviews/<id>.json          人工最终标注
   approved/<id>.txt          训练唯一来源（仅 approved 照片生成）
   classes.json               canonical → class_id
   review_queue.json          待审队列（按不确定度排序）
   review_events.jsonl        人工动作追加日志（before/after）
   label_eval.json / recog_eval.json   评测报告
.warehouse/db.sqlite   元数据仓库（8 表）
.datasets/v1/          YOLO 数据集：images/{train,val}, labels/{train,val}, data.yaml
.models/smoke/weights/ 训练权重 best.pt/last.pt
```

## 5. 数据仓库 schema（8 表 + 追加约束）

`sku_catalog · asset · annotation · auto_label · review_event · dataset_version · model_version · recognition_run`

- `annotation / auto_label / review_event` 三表在 DB 层建触发器，**禁止 UPDATE/DELETE**（红线机检）。
- 向量不在该库（在 `.kb/vectors.npy`；升 pgvector 时迁入）。
- JSON 字段以 TEXT 存，跨 SQLite/PG 可移植。

## 6. 红线汇总

1. 原始资产只读（`paths.assert_writable` 拦截）。
2. 自动预测 ≠ 金标；训练只读 `approved/`。
3. 人工动作只追加（`review_events.jsonl` + DB 触发器）。
4. 检索只召回，裁决 = 硬过滤 + VLM 终审。
5. 金标/训练/验证零泄漏（按照片切分）。
6. 密钥只经 `.env`。

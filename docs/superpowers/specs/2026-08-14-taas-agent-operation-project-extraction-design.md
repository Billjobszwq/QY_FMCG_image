# TaaS by Agent Operation 项目剥离与版本冻结设计

## 1. 目标

将截至 2026-08-14 的完整开发状态从
`<legacy-workspace>` 剥离到
`<project-root>`，后者作为后续开发主目录。

新目录必须：

- 保留现有 Git 历史并继续关联 `https://github.com/Billjobszwq/QY_FMCG_image.git`；
- 以当前 `feat/nextgen-training-cycle-v2` 的 `42db8331` 为业务基线；
- 完整保留系统源码、配置模板、迁移、测试、开发文档和必要静态资源；
- 在本地明确分离训练数据、识别模型和运行时数据；
- 上传版本不包含用户照片、用户数据、真实凭据、数据库、日志、标注队列、训练数据实体或模型权重；
- 从新目录可安装、测试、构建并继续开发。

## 2. 已核对的源码范围

当前版本的核心代码不是单一图像识别工具，而是 Graph+Loop 智能业务平台与 FMCG 视觉 Domain Pack 的组合。剥离必须保留以下全部内容。

### 2.1 Python 系统源码

`src/` 共 272 个 Python 文件，全部迁移：

- `src/platform/`：平台内核、API、认证、任务、工作流、Agent、资产、分析和质量门；
- `src/modules/`：训练控制、训练治理、数据工厂、标注、系统健康、NextGen 数据和 FMCG Domain Pack；
- `src/training/`：检测、分类、分割、VLM 训练与模型治理；
- `src/eval/`：基线、真值框、级联、召回、严格 IoU 和参数评测；
- `src/sam_assist/`：SAM 提示、候选、损失、运行时与证据；
- `src/ls_platform/` 与 `src/ls_ml_backend/`：Label Studio 平台与 ML Backend；
- `src/cascade/`、`src/recognize/` 与 `src/pipeline/`：识别级联和在线识别链；
- `src/data/`、`src/data_quality/` 与 `src/data_governance/`：数据协议、质量门和禁用身份治理；
- `src/catalog/`、`src/models/`、`src/composition/`、`src/review/`、`src/labeling/`、`src/field/` 和 `src/common/`。

### 2.2 Web 应用

`web/` 全部源码迁移，包含 29 个业务页面以及平台壳、路由、API 客户端、设计令牌和响应式布局。业务页面覆盖：

- 主管工作台、任务看板、Agent 中心和 Graph 运行；
- 图像识别、标注、训练控制、模型运行时和级联任务；
- 导入、资产、新包装、调研、BI、财务、地理、对账和帮助文档；
- 工作流、工作流画布、系统状态和运营客户上下文。

### 2.3 开发与验证资产

- `scripts/`：114 个数据构建、训练、评测、迁移、门禁、回放和运维脚本；
- `tests/`：175 个测试文件、1,553 个测试函数，覆盖 contract、platform、unit 和 promotion；
- `configs/`、`migrations/`、`compose.yaml`、`pyproject.toml`、`web/package.json` 和锁文件；
- `docs/` 中的架构、运维、用户手册、决策和实施文档，但不包含用户数据或现场证据的文件。

## 3. 新目录结构

```text
TaaS by Agent Operation/
├── src/                         # Python 系统源码，Git 跟踪
├── web/                         # Web 前端源码，Git 跟踪
├── tests/                       # 自动化测试，Git 跟踪
├── scripts/                     # 数据/训练/运维脚本，Git 跟踪
├── configs/                     # 非敏感配置模板，Git 跟踪
├── migrations/                  # 数据库迁移，Git 跟踪
├── docs/                        # 清理后的文档，Git 跟踪
├── data/                        # 去标识化 SKU 目录/别名等主数据
├── training-data/               # 本地训练资产，数据实体不进 Git
│   ├── raw/
│   ├── processed/
│   ├── evaluation/
│   └── README.md                # 只记录类型、位置、版本规则
├── recognition-models/           # 本地模型资产，权重不进 Git
│   ├── production/
│   ├── candidates/
│   ├── foundation/
│   └── README.md                # 只记录版本和本地恢复规则
├── runtime/                     # 数据库/日志/缓存/临时输出，不进 Git
├── .env.example                 # 仅字段和安全说明
├── pyproject.toml
└── compose.yaml
```

## 4. 本地资产分类

### 4.1 训练数据

以下资产只放入新目录的 `training-data/`，由 `.gitignore` 硬性排除：

- 原始照片、Excel 清单和历史批次；
- `.datasets/`、`.datasets_nextgen/`、`.training_data/` 与 `.batch3_clean/`；
- crop dataset、micro-gold、质量筛选结果和评测样本；
- 知识库参考图和本地标注资产。

提交中的 `training-data/README.md` 不记录用户姓名、照片文件名、本地绝对路径、标注内容或单条记录。

### 4.2 识别模型

以下资产只放入 `recognition-models/`，由 `.gitignore` 硬性排除：

- 以 `registry/bundles/CURRENT.json` 为选择状态的唯一事实源：当前生产 bundle 为
  `prod_v4_best_r1`，上一个/回滚 bundle 为 `prod_20260805_v5_r1`；两者都只作为本地资产，
  本次剥离不上传权重、不修改 `CURRENT.json`、不执行模型切换；
- 候选 detector、classifier、segmenter 和 VLM adapter；
- YOLO 基础权重和 SAM checkpoint；
- 历史可恢复权重。

提交中只保留模型类型、版本 ID、状态和恢复流程，不保留权重、adapter、评测样本或用户来源的推理结果。

### 4.3 运行时数据

以下内容不进入新的版本文件树，也不从旧工作区复制到可提交位置：

- `.env` 与任何真实密钥；
- Label Studio 数据库、平台数据库、备份、日志和 PID；
- 用户任务、审核队列、导入记录、浏览器证据和运行报告；
- Python 虚拟环境、`node_modules`、构建产物和各类缓存。

## 5. Git 版本策略

1. 使用本地源仓库创建新工作目录，保留所有现有提交历史。
2. 将 `origin` 校验为 `https://github.com/Billjobszwq/QY_FMCG_image.git`。
3. 从当前开发基线创建 `codex/taas-agent-operation-v1`。
4. 不修改、不删除、不强制推送旧历史。
5. 清理新版本文件树中的用户数据、运行证据和不应跟踪的二进制资产。
6. 建立严格 `.gitignore` 和可提交资产白名单。
7. 提交冻结版，推送新分支，并创建注释标签 `app-v0.3.0-taas.1`。
8. 未经用户明确授权，不合并 `main`、不部署、不切换生产模型。

## 6. 用户数据清理规则

新版本的 Git 跟踪文件必须通过以下规则：

- 禁止跟踪照片、视频、音频、Excel、CSV、JSONL 业务明细、SQLite/DB 和模型权重；
- 禁止跟踪识别请求/结果、客户 ID、上传件名、照片 ID、追踪 ID 和真实运行证据；
- 禁止跟踪真实令牌、密码、cookie、连接串和本机绝对路径；
- 测试数据必须为显式虚构、最小化且不能反推现场用户；
- 前端演示资源如无法证明为非用户数据，就从 Git 删除或替换为中性占位资源。

本次只保证新分支与新标签所指向的文件树无用户数据，不改写旧 Git 历史。

## 7. 验收标准

### 7.1 完整性

- 新目录包含原版本全部已跟踪源码、测试、脚本、迁移和配置，除非文件被明确归类为用户数据或运行证据；
- Python 包、Web 页面、脚本和测试文件的迁移清单可对账；
- 当前生产模型和后续训练资产的本地位置有明确说明。

### 7.2 可开发性

- Python 依赖可从 `pyproject.toml` 安装；
- 默认 hermetic pytest 套件通过；
- Web 依赖安装与生产构建通过；
- 代码中不依赖旧工作区绝对路径；
- 从新提交创建的临时克隆可完成无本地资产的基础测试与构建。

### 7.3 版本卫生

- `git status --short` 在冻结提交后为空；
- `git ls-files` 不包含禁止文件类型和本地资产实体；
- 敏感信息和用户数据扫描无确认泄漏；
- 分支已推送到 `origin`，本地与远端 commit SHA 一致；
- 注释标签 `app-v0.3.0-taas.1` 指向同一冻结提交。

## 8. 非目标

- 不重写旧 Git 历史；
- 不上传训练数据、模型或用户数据；
- 不合并 `main`；
- 不部署到任何环境；
- 不改变当前生产模型、数据库或在线服务状态。

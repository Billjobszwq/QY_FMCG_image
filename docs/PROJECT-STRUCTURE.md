# 项目结构

本文是当前干净开发基线的源码索引。所有路径均相对于仓库根目录；本地资产不属于源码树，见 [`LOCAL-ASSETS.md`](LOCAL-ASSETS.md)。

## 八个业务域

| 业务域 | 主要实现位置 |
|---|---|
| `platform-kernel` | `src/platform/` 的契约、注册表、API、权限、资产与执行内核 |
| `graph-loop` | `src/platform/kernel/`、`src/platform/loops/`、`src/platform/agents/` 和工作流 API |
| `training-control` | `src/modules/training_control/`、`src/modules/training_gov/`、`src/training/` |
| `dataset-factory` | `src/modules/dataset_factory/`、`src/modules/nextgen_data/`、`src/data/` |
| `fmcg-recognition` | `src/modules/fmcg/`、`src/recognize/`、`src/cascade/` |
| `labeling-review` | `src/labeling/`、`src/review/`、`src/ls_ml_backend/`、`src/ls_platform/` |
| `model-runtime` | `src/models/`、`src/platform/model_runtime.py`、识别与模型 API |
| `web-workbench` | `web/src/` 的页面、模块 UI 注册表、设计 token 和主管工作台 |

## Python 一级包（20）

这里的“一级包”指 `src/` 下的 20 个代码目录；其中既包含常规包，也包含由项目打包配置发现的命名空间目录。

| 路径 | 职责 |
|---|---|
| `src/cascade/` | 级联分类、数据集构建、微调和推理 |
| `src/catalog/` | SKU 目录、别名、知识库与命名归一化 |
| `src/common/` | 配置、路径、哈希、外部接口和发布树审计 |
| `src/composition/` | 组合数据的构建与服务入口 |
| `src/data/` | 数据协议、仓库、清洗和质量门 |
| `src/data_governance/` | 数据身份与禁止项治理 |
| `src/data_quality/` | 数据质量规则与证据计算 |
| `src/eval/` | 检测、识别、级联和零样本评估 |
| `src/field/` | 外勤照片输入适配 |
| `src/labeling/` | 标注定位、分配、提案、审核和工作台 |
| `src/ls_ml_backend/` | Label Studio 模型后端 |
| `src/ls_platform/` | Label Studio 平台集成 |
| `src/models/` | 模型 bundle 契约与本地解析 |
| `src/modules/` | 可插拔业务模块与领域服务 |
| `src/pipeline/` | 识别/评测流水线入口 |
| `src/platform/` | 平台内核、Graph+Loop、Agent、API 与控制面 |
| `src/recognize/` | 在线识别 API、服务和推理适配 |
| `src/review/` | 人工审核队列、导出与审核载荷 |
| `src/sam_assist/` | SAM 辅助标注、候选框和提示 |
| `src/training/` | 数据集构建、训练、门禁、监控与 VLM 训练 |

## Web 页面（29）

页面源码统一位于 `web/src/pages/`，路由由 `web/src/platform/ui_registry.tsx` 和 `web/src/App.tsx` 组装。以下分组覆盖当前全部 29 个页面文件。

### 平台首页、主管与帮助（6）

- `Home`：主管工作台首页
- `Overview`：系统总览
- `SystemStatus`：系统状态
- `TaskBoard`：任务看板兼容页
- `AgentCenter`：Agent 中心
- `HelpDocs`：帮助与文档

### 工作流与运行（3）

- `Workflow`：工作流入口
- `WorkflowCanvas`：工作流画布
- `GraphRuns`：Graph/Loop 运行中心

### 识别、标注、模型与训练（8）

- `Vision`：即时识别与视觉领域入口
- `CascadeTasks`：级联识别任务
- `Annotation`：标注与审核
- `LabelStudioHub`：Label Studio 集成入口
- `NewPackaging`：新旧包装管理
- `ModelRuntime`：模型驻留与运行时状态
- `Training`：训练视图
- `TrainingControl`：训练控制面

### 数据、导入、用量与对账（4）

- `Assets`：数据资产台账
- `ImportCenter`：统一导入中心
- `UsageWorkbench`：用量工作台
- `ReconciliationPanel`：证据与用量对账

### 分析和经营业务（8）

- `Analytics`：分析入口
- `BIWorkbench`：BI 工作台
- `Finance`：财务与结算
- `Geo`：位置与外勤
- `GeoMap`：地图视图
- `Survey`：调研执行
- `SurveyBuilder`：问卷设计
- `IamMaster`：账号、权限与主数据

## 测试套件（4）

| 路径 | 验证范围 |
|---|---|
| `tests/unit/` | 单个算法、适配器、守卫与工具的快速单元测试 |
| `tests/contract/` | 跨模块接口、数据不变量和仓库结构合同 |
| `tests/platform/` | 平台 API、Graph+Loop、Agent、领域模块和持久化集成 |
| `tests/promotion/` | 面向发布/推广产物的验收测试 |

默认入口是 `.venv/bin/python -m pytest`；真实宿主硬件探针使用独立 marker，不包含在默认 hermetic 套件中。

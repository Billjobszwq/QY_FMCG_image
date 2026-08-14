# TaaS by Agent Operation

这是 QY 图像识别与 Agent 业务操作系统的干净开发基线。仓库保存系统源码、配置模板、测试和开发文档；训练数据、模型文件、运行状态和用户数据只保留在本机，不进入 Git。

## 系统业务域

| 业务域 | 职责 |
|---|---|
| `platform-kernel` | 平台契约、模块注册、权限、API 与执行内核 |
| `graph-loop` | Graph+Loop 编排、运行、检查点、工作流和 Agent 协作 |
| `training-control` | 训练计划、资源租约、质量门、评估与发布治理 |
| `dataset-factory` | 数据摄取、快照、加工、质量检查与数据集构建 |
| `fmcg-recognition` | FMCG 货架检测、级联识别、SKU 检索与质量策略 |
| `labeling-review` | 标注提案、人工审核、金标准与 Label Studio 适配 |
| `model-runtime` | 模型 bundle、驻留、推理服务与显式切换边界 |
| `web-workbench` | Web 工作台、业务页面、主管 Agent 与证据界面 |

完整的源码和页面清单见 [`docs/PROJECT-STRUCTURE.md`](docs/PROJECT-STRUCTURE.md)，本地数据和模型布局见 [`docs/LOCAL-ASSETS.md`](docs/LOCAL-ASSETS.md)。

## 安装

要求 Python 3.11–3.13 和当前 Node.js LTS。Python 开发环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Web 依赖使用锁文件安装：

```bash
npm --prefix web ci
```

复制配置模板并填写本机值；真实密钥只写入被 Git 忽略的 `.env`：

```bash
cp .env.example .env
```

## 恢复本地资产布局

克隆仓库后先查看计划，再创建标准目录和旧路径兼容链接：

```bash
python3 scripts/bootstrap_local_assets.py --dry-run
python3 scripts/bootstrap_local_assets.py
```

脚本不会覆盖已有路径。训练数据放入 `training-data/`，模型放入 `recognition-models/`，数据库、日志、缓存和审核队列等状态放入 `runtime/`；这些目录的实际内容均不提交。

## 测试与构建

```bash
.venv/bin/python -m pytest
npm --prefix web run build
python3 scripts/audit_release_tree.py --root . --format json
```

默认 Python 测试分为 `unit`、`contract`、`platform`、`promotion` 四类。发布树审计必须返回零 finding，Web build 必须成功后才能形成版本基线。

## 敏感数据规则

- 不提交用户/客户照片、标注、表格、导入文件、审核记录、日志或数据库。
- 不提交训练集、评估集、模型权重、checkpoint 或模型 bundle。
- 不提交 `.env`、访问令牌、密码、Cookie、私有地址或本机绝对路径。
- 示例和文档只使用中性占位符；需要共享的样例必须先脱敏并通过发布树审计。
- 生产模型切换、部署和数据迁移是独立审批动作，Git 版本提交不会触发这些动作。

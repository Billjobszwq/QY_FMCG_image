# Git Version Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不把训练图片、数据库、凭据、运行日志和大模型权重直接提交到普通 Git 的前提下，为 LLM-Image 建立可审计、可回滚、可恢复的源码版本控制体系。

**Architecture:** 采用“双轨版本控制”：Git 只管理源码、测试、迁移、文档和小型声明文件；训练数据与模型制品进入 DVC/私有 MinIO 或等价对象存储，Git 仅保存内容哈希、manifest、DVC 指针和模型 bundle 元数据。模型发布必须同时关联 Git commit、数据版本和 bundle manifest，不能只依赖可变路径 `best.pt`。

**Tech Stack:** Git、Git LFS（仅限少量固定二进制样例）、DVC、私有 MinIO/兼容 S3 对象存储、pytest、Python AST/compileall、secret scanning、CI。

---

## 0. 本手册的执行边界

本文件是实施手册，不代表 Git 已经初始化。本次审查不执行以下动作：

- 不运行 `git init`、`git add`、`git commit`、`git remote add` 或 `git push`。
- 不修改现有 `.gitignore`、依赖文件、源码、数据或模型。
- 不上传任何本地文件到远端。
- 不删除现有训练数据、缓存、日志、数据库或历史模型。

当前只读检查结果：项目目录还不是 Git repository；源码、测试、迁移、配置、数据声明和文档合计约 1.7 MiB，适合进入 Git；本地数据和制品目录合计达到数十 GiB，必须留在 Git 之外。

## 1. 版本控制对象边界

### 1.1 应进入 Git 的内容

| 类型 | 当前路径 | 规则 |
|---|---|---|
| 应用源码 | `src/` | 全部纳入，排除 `__pycache__`、`.pyc` |
| 自动化测试 | `tests/`、`conftest.py` | 全部纳入，排除缓存 |
| 数据库迁移 | `migrations/` | 全部纳入；迁移文件发布后只追加，不回写历史 |
| 运维脚本 | `scripts/` | 纳入文本脚本；本地日志和 PID 文件不纳入 |
| 静态配置 | `configs/`、`compose.yaml`、`pyproject.toml` | 纳入无密钥版本；镜像版本应固定，不使用 `latest` |
| 小型业务声明 | `data/sku_registry.json`、`data/sku_aliases.json`、`data/sku_classes.json` | 纳入；变更必须代码评审并生成语义版本 |
| 项目文档 | `docs/`、`2026-07-31-general-sku-recognition-system.md` | 全部纳入 |
| 环境模板 | `.env.example` | 只保留假值和说明，不放真实 token |
| 忽略与属性规则 | `.gitignore`、`.gitattributes` | 纳入并受保护 |
| 数据/模型指针 | `*.dvc`、`dvc.yaml`、`dvc.lock`、经过脱敏的 manifest | 纳入，但不纳入实际大文件 |

### 1.2 禁止进入普通 Git 的内容

| 类型 | 当前路径/模式 | 原因 | 归档方式 |
|---|---|---|---|
| 真实凭据 | `.env`、`.env.*`、`.label-studio/.env`、本地工具设置 | 泄密风险 | 本机权限 600；生产使用 secret manager |
| 原始照片与 Excel | `照片1106/`、`照片1107/`、`百事&可口/`、`搭建初期P1/`、`实景照片.xlsx`、三批训练数据 Excel | 隐私、体积、频繁变化 | DVC + 私有对象存储，Git 保存哈希/指针 |
| 数据集物化目录 | `.training_data/`、`.batch3_clean/`、`.datasets/`、`crop_dataset/`、`crop_dataset_yolo/`、`batch3_gray/` | 可重建、大体积 | DVC 或构建 manifest |
| 模型权重 | `.models/`、`best/`、`*.pt`、`*.pth`、`*.onnx`、`*.engine` | 大体积、发布制品 | 模型 registry/MinIO，Git 保存 bundle manifest |
| 运行数据库 | `.warehouse/`、`.label-studio/*.sqlite3`、`*.db`、`*.sqlite*` | 含业务状态，无法安全 merge | 备份系统；schema 进入 migrations |
| 运行缓存/报告 | `.eval/`、`.kb/`、`.field/`、`.labels/`、`.platform/`、日志、截图 | 可重建或含运行数据 | 审计存储/对象存储；必要摘要写入 docs |
| 本机文件 | `.DS_Store`、`__pycache__/`、`.pytest_cache/`、`.claude/settings.local.json`、`UI风格设计-1/`、`~/` | 环境相关或无源码价值 | 留在本机 |

### 1.3 Git LFS 与 DVC 的职责分界

- Git LFS 只用于少量、固定、经过脱敏的回归测试图片，例如每个关键场景 1～3 张；单文件建议不超过 50 MiB，总量设置仓库配额。
- 训练/验证图片、Excel、完整 checkpoint 和 bundle 不应因为“能用 LFS”就进入 LFS；这些资产有数据血缘、分区、复现实验和访问控制需求，应由 DVC/模型 registry 管理。
- 模型 bundle 发布到对象存储后，Git 记录 `bundle_id`、完整 SHA256、数据版本、代码 commit、阈值、类别顺序和评估报告路径。

## 2. 仓库治理规范

### 2.1 分支

- `main`：唯一稳定主分支，禁止直接 push，要求 CI 通过和至少一次评审。
- `feat/recognize-bundle-validation` 一类分支：功能开发。
- `fix/training-dataset-hash` 一类分支：缺陷修复。
- `exp/e2-class-agnostic-detector` 一类分支：训练实验配置、分析脚本和实验报告；不提交权重。
- `docs/git-governance` 一类分支：纯文档变更。
- `hotfix/bundle-rollback` 一类分支：生产紧急修复；合并后必须补测试与复盘。

分支应短生命周期。一个分支只解决一个问题；训练实验不得混入无关服务改造。

### 2.2 提交信息

采用 Conventional Commits：

```text
feat(recognize): add bundle class-order validation
fix(training): include label bytes in dataset hash
test(cascade): reject high-confidence unknown predictions
docs(training): record E03 detector oracle result
chore(deps): regenerate portable lock file
```

每个提交必须满足：能够解释“为什么改”、不含凭据和大文件、相关测试通过、文档与行为一致。避免 `update`、`fix bug`、`latest` 等不可追溯信息。

### 2.3 标签与发布

- 应用版本：`app-vMAJOR.MINOR.PATCH`。
- 数据版本：`data-vYYYYMMDD.N`，实际数据由 DVC hash 唯一确认。
- 模型 bundle 标签以 `model-` 开头，例如 `model-prod_20260804_v4_r2`。
- 标签必须是 annotated tag，并写明 Git commit、DVC revision、bundle MANIFEST SHA256、gold 版本和发布门禁结果。
- 不允许用同一个 tag 指向新的 commit，不允许覆盖已经发布的 bundle。

## 3. Task 1：建立仓库前只读审计

**Files:**
- Inspect: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.gitignore`
- Inspect: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.env.example`
- Inspect: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/requirements-lock.txt`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.gitattributes`

- [ ] **Step 1: 确认目录尚未被初始化**

```bash
git rev-parse --show-toplevel
```

Expected: 初始化前返回非零并提示不是 Git repository；若已经是仓库，停止后续 `git init`，先审计现有历史和 remote。

- [ ] **Step 2: 生成大文件清单，不修改文件**

```bash
find . -type f -size +20M -not -path './.git/*' -print
du -sh .batch3_clean .training_data .models crop_dataset crop_dataset_yolo .kb .eval .datasets 2>/dev/null
```

Expected: 所有超过 20 MiB 的文件都有明确去向，不在后续 Git 暂存白名单内。

- [ ] **Step 3: 做密钥扫描**

推荐在受控环境安装并运行 `gitleaks`；在未安装工具时，至少执行下列只读初筛：

```bash
rg -n --hidden --glob '!**/.git/**' --glob '!*.sqlite*' --glob '!*.pt' --glob '!*.pth' '(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16}|secret[_-]?key|access[_-]?token|password\s*=)' .
```

Expected: 命中逐项人工判断；任何真实密钥必须先轮换和移出工作树，不能仅依靠 `.gitignore`。

- [ ] **Step 4: 检查依赖锁可移植性**

```bash
rg -n '@ file://' requirements-lock.txt
```

Expected: 当前会命中约 36 条本机路径；在首次稳定版本前重新生成可移植锁文件，不能把当前文件当作跨机器可复现证据。

## 4. Task 2：完善忽略规则和文本属性

**Files:**
- Modify later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.gitignore`
- Create later: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image/.gitattributes`

- [ ] **Step 1: 用以下策略补齐 `.gitignore`**

执行者应在保留现有有效规则的基础上合并，不要覆盖用户已有条目：

```gitignore
# OS / editor / Python
.DS_Store
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.venv/
venv/

# Secrets and machine-local settings
.env
.env.*
!.env.example
.label-studio/.env
.claude/settings.local.json
~/

# Runtime databases, locks and logs
*.db
*.db-*
*.sqlite
*.sqlite3
*.sqlite3-*
*.log
*.pid
.warehouse/
.label-studio/
.platform/

# Generated data, caches and evaluations
.batch3_clean/
.training_data/
.datasets/
.data_protocol/*.bak.json
.eval/
.field/
.kb/
.labels/
crop_dataset/
crop_dataset_yolo/
batch3_gray/
bad_samples/

# Model artifacts
.models/
best/
*.pt
*.pth
*.onnx
*.engine
*.safetensors

# Raw business assets
照片1106/
照片1107/
百事&可口/
搭建初期P1/
UI风格设计-1/
实景照片.xlsx
第一批训练数据.xlsx
第二批训练数据.xlsx
第三批训练数据.xlsx
```

若决定把 `.data_protocol/gold_holdout.json` 作为协议声明纳入 Git，应显式允许该小文件，但必须确认它不含敏感路径；真正 gold 图片仍由 DVC 管理。

- [ ] **Step 2: 创建 `.gitattributes`**

```gitattributes
* text=auto eol=lf
*.sh text eol=lf
*.py text eol=lf
*.md text eol=lf
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
*.toml text eol=lf
*.sql text eol=lf
*.plist text eol=lf
*.jpg binary
*.jpeg binary
*.png binary
*.xlsx binary
*.pt binary
*.pth binary
*.sqlite binary
*.sqlite3 binary
```

- [ ] **Step 3: 在 Task 3 完成 `git init` 后验证忽略行为**

```bash
git check-ignore -v .env .label-studio/.env .models/classifier/best.pt crop_dataset_yolo/dataset_summary.json 第二批训练数据.xlsx
git check-ignore -v .env.example
```

Expected: 第一条中的所有敏感/大文件均被忽略；`.env.example` 不应被忽略。`dvc.lock`、`uv.lock` 等可复现性锁文件不能被通用 `*.lock` 规则误伤。

## 5. Task 3：初始化本地源码仓库

**Files:**
- Add: 仅第 1.1 节允许进入 Git 的文件

- [ ] **Step 1: 在项目负责人确认后初始化**

```bash
git init -b main
git config core.autocrlf input
git config pull.ff only
```

- [ ] **Step 2: 只使用显式白名单暂存，禁止 `git add .`**

```bash
git add .gitignore .gitattributes .env.example pyproject.toml compose.yaml conftest.py
git add src tests migrations scripts configs data docs
git add 2026-07-31-general-sku-recognition-system.md
```

如果某个列出的路径不存在，先核实实际结构并从命令中移除；不要用通配式全量暂存作为替代。

- [ ] **Step 3: 审核暂存内容**

```bash
git status --short
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
```

Expected: 不出现 `.env`、SQLite、Excel、照片、`*.pt`、`*.pth`、日志、运行目录或本机设置。

- [ ] **Step 4: 设置大文件保险门**

```bash
git diff --cached --numstat | awk '$1 == "-" || $2 == "-" {print $3}'
find . -path ./.git -prune -o -type f -size +20M -print
```

任何二进制或超过 20 MiB 文件出现在暂存区时，停止提交；例如误暂存 `yolo26m.pt` 时执行 `git restore --staged -- yolo26m.pt`，再修正忽略规则。不得删除原文件。

- [ ] **Step 5: 跑基线验证**

```bash
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy python -m pytest -p no:cacheprovider tests -q
python -m compileall -q src tests
```

Expected: 当前基线为 22 passed；compileall 返回 0。若结果不同，将失败记录到 `docs/`，不要把红色基线伪装为成功。

- [ ] **Step 6: 建立初始提交和基线标签**

```bash
git commit -m "chore(repo): establish source-only version control baseline"
git tag -a app-v0.1.0 -m "Initial source-only baseline; data and model artifacts remain external"
```

## 6. Task 4：配置私有远端和分支保护

**Files:**
- Modify later: 远端仓库设置和 CI 配置

- [ ] **Step 1: 确认远端是私有仓库**

项目负责人应先创建空的私有仓库，并在当前 shell 显式设置地址：

```bash
test -n "${GIT_REMOTE_URL:?Set GIT_REMOTE_URL to the approved private repository URL}"
git remote add origin "$GIT_REMOTE_URL"
git remote -v
```

Expected: fetch/push 都指向经批准的私有远端；不得把项目误推到个人公开仓库。

- [ ] **Step 2: 首次推送前再次审计完整历史**

```bash
git ls-files | rg '(^|/)(\.env|.*\.sqlite3?|.*\.db|.*\.pt|.*\.pth|.*\.xlsx)$'
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | awk '$1 == "blob" && $3 > 20971520 {print}'
```

Expected: 第一条无真实敏感/大文件；第二条无超过 20 MiB 的 blob。若有命中，在任何 push 前停止并由负责人决定是否重写尚未发布的本地历史。

- [ ] **Step 3: 经用户明确批准后首次 push**

```bash
git push -u origin main
git push origin app-v0.1.0
```

- [ ] **Step 4: 在托管平台配置保护规则**

必须启用：禁止 force push、禁止删除 `main`、至少一项 CI 必须成功、合并前解决对话、限制直接 push、保留 tag 不可变。若团队只有一人，可暂时取消“第二人批准”，但不能取消 CI 和禁止 force push。

## 7. Task 5：CI 与提交前门禁

**Files:**
- Create later: `.github/workflows/ci.yml` 或实际托管平台等价配置
- Create later: `.pre-commit-config.yaml`

- [ ] **Step 1: CI 建立四层门禁**

1. 单元/契约测试：`python -m pytest tests -q`。
2. 语法检查：AST 或 `python -m compileall -q src tests`。
3. secret scan：完整 Git diff 和历史扫描。
4. 大文件/禁入路径：拒绝 `.env`、数据库、模型、Excel、原图以及超过 20 MiB 的非 LFS blob。

- [ ] **Step 2: 补充模型系统关键回归测试后再提升保护强度**

CI 最少应新增 bundle hash、registry 顺序、unknown 拒识、gold 零泄漏、dataset hash 包含 label、monitor cache 和 webhook 并发幂等测试。当前 22 项测试不足以证明训练/发布协议安全。

- [ ] **Step 3: 依赖可复现性**

从干净 Python 3.13 环境生成不含 `file://` 的锁文件。可选方案按优先级：

1. `uv lock` 生成 `uv.lock` 并在验证后单独提交；
2. `pip-compile pyproject.toml -o requirements-lock.txt`，验证不含 `file://` 后再单独提交；
3. 若特定 macOS 包必须本地安装，将其放入平台专属安装说明，不写绝对本机路径。

在第二台干净机器或临时环境完成一次安装和测试，才可声明 lock 可复现。

## 8. Task 6：数据、实验和模型版本联动

**Files:**
- Create later: `dvc.yaml`
- Create later: `dvc.lock`
- Create later: `docs/model-release-template.md`
- Track later: `.data_protocol/*.json` 中不含敏感内容的协议声明

- [ ] **Step 1: 配置 DVC 私有远端**

优先复用受控 MinIO，但凭据只放环境变量或 secret manager，不写进 `.dvc/config` 的 Git 版本。DVC 应至少管理：原始训练资产清单、清洗数据集、训练/验证 split、gold-v2、checkpoint 和发布 bundle。

- [ ] **Step 2: 为每个数据版本生成不可变 manifest**

manifest 至少包含：

- `dataset_id` 和完整 SHA256；
- 每个输入文件的相对路径、大小、SHA256；
- 图片与 label 内容；
- registry 版本与 208/209 类有序列表；
- train/val/gold 的门店、采集会话和 SHA 去重结果；
- builder Git commit、参数、seed 和构建时间；
- 实际磁盘计数与失败清单。

- [ ] **Step 3: 实验记录绑定三个不可变版本**

每个实验 E0～E7 必须记录：

```text
code_commit=git rev-parse HEAD 返回的完整 40 位 SHA
data_revision=dvc.lock 中对应阶段的精确 revision 或完整 dataset SHA256
registry_sha256=data/sku_registry.json 的完整 SHA256
```

不得只记录模型文件名、16 位 hash 前缀或可变的 `best.pt` 路径。

- [ ] **Step 4: 发布模型 bundle**

bundle manifest 必须额外记录 detector/classifier 有序类别映射、阈值、校准参数、gold-v2 报告、延迟/RSS、Git tag 和 DVC revision。发布前逐文件校验；发布后模型目录只读。

- [ ] **Step 5: 建立恢复演练**

每个正式版本至少演练一次：

1. 在新的空目录 clone 指定 Git tag；
2. 从 DVC/对象存储拉取指定数据和 bundle；
3. 校验 manifest SHA256；
4. 运行测试和 bundle verify；
5. 以只读方式加载模型并复跑固定 smoke 样本；
6. 比较输出、环境和性能报告。

无法完成上述恢复的版本不能称为“可复现发布”。

## 9. Task 7：日常开发操作模板

- [ ] **开始任务**

```bash
git switch main
git pull --ff-only
git switch -c docs/training-gold-v2-protocol
```

- [ ] **提交前**

```bash
git status --short
git diff --check
PYTHONDONTWRITEBYTECODE=1 XONSH_HISTORY_BACKEND=dummy python -m pytest -p no:cacheprovider tests -q
git diff --stat
```

- [ ] **只暂存本任务文件**

```bash
git add docs/training-gold-v2-protocol.md
git diff --cached --check
git commit -m "docs(training): define gold-v2 isolation protocol"
```

- [ ] **合并后标记模型相关版本**

只有发布门禁全部通过时才创建 `model-` 前缀的 bundle 标签，例如 `model-prod_20260804_v4_r2`；一般代码提交不要滥用模型标签。

## 10. 验收标准

Git 实施只有同时满足以下条件才能关闭：

- [ ] `git status` 清晰，无意外大文件或秘密文件。
- [ ] `git ls-files` 不包含 `.env`、SQLite、训练 Excel、原图、模型权重和运行日志。
- [ ] Git 历史无超过 20 MiB 的意外 blob。
- [ ] 私有远端启用 `main` 保护、禁止 force push，并有必要 CI。
- [ ] 依赖锁不含本机 `file://` 路径，能够在干净环境安装。
- [ ] 数据、代码、registry、模型 bundle 和评估报告能通过不可变 ID 互相追溯。
- [ ] 新机器完成一次 clone + 数据/模型拉取 + hash 校验 + smoke 测试。
- [ ] 回滚演练能够从当前 bundle 切回 previous，并能确认 Git/DVC 对应版本。

## 11. 回滚与事故处理

- 发现未 push 的敏感文件：先轮换密钥，再从暂存/本地历史中移除；保留业务原文件，不做删除。
- 发现已经 push 的密钥：立即吊销/轮换，通知仓库管理员，按托管平台流程重写历史；`.gitignore` 不是补救措施。
- 发现大模型已入历史：停止后续 push，由负责人决定 Git LFS 迁移或在确认无其他协作者依赖后清理历史。
- 发现数据指针错误：不要覆盖旧 DVC 版本；新建修正版数据版本并在报告中标记旧版本失效原因。
- 生产故障回滚：优先切换 immutable bundle；代码回滚通过正常 revert commit，不使用共享分支上的 `reset --hard` 或 force push。

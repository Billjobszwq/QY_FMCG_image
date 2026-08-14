# TaaS by Agent Operation Project Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前完整开发状态剥离到 `TaaS by Agent Operation`，使新目录可继续本地开发，并向现有 GitHub 仓库推送一个不含用户数据、训练数据实体或模型权重的冻结版。

**Architecture:** 使用本地 Git 克隆保留当前所有历史和未推送提交，在用户指定的新目录建立 `codex/taas-agent-operation-v1` 分支。代码保留原有导入结构，本地大资产按训练数据、识别模型和运行时归档，通过不进 Git 的兼容链接支持旧路径。可重复运行的发布文件树审计在提交前拦截禁止路径、禁止文件类型、用户运行证据、凭据和旧工作区绝对路径。

**Tech Stack:** Git/GitHub CLI、Python 3.11+、Pytest、React/Vite/TypeScript、APFS clone-copy、SHA-256。

---

### Task 1: 建立完整可追溯的新工作目录

**Files:**
- Source repository: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image`
- Create repository: `/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation`

- [ ] **Step 1: 记录源基线和源码清单**

```bash
git -C '/Users/zhangweiqi/Documents/QY/项目/LLM-Image' rev-parse HEAD
git -C '/Users/zhangweiqi/Documents/QY/项目/LLM-Image' ls-files 'src/**' 'web/**' 'tests/**' 'scripts/**' | sort > /tmp/taas-source-files.txt
```

Expected: HEAD 包含设计文档提交 `cef2998e`。

- [ ] **Step 2: 克隆到指定目录并创建分支**

```bash
git clone --no-hardlinks '/Users/zhangweiqi/Documents/QY/项目/LLM-Image' '/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation'
git -C '/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation' remote set-url origin 'https://github.com/Billjobszwq/QY_FMCG_image.git'
git -C '/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation' switch -c codex/taas-agent-operation-v1
```

Expected: 新目录 HEAD 与源目录 HEAD 相同，`origin` 只指向 GitHub。

- [ ] **Step 3: 核对模块数**

```bash
test "$(rg --files src -g '*.py' | wc -l | tr -d ' ')" = 272
test "$(rg --files web/src/pages -g '*.tsx' | wc -l | tr -d ' ')" = 29
test "$(rg --files scripts -g '*.py' -g '*.sh' | wc -l | tr -d ' ')" = 114
test "$(rg --files tests -g 'test_*.py' | wc -l | tr -d ' ')" = 175
```

Expected: 四个断言全部通过。

### Task 2: 用 TDD 锁定新版本的数据卫生规则

**Files:**
- Create: `src/common/release_tree_audit.py`
- Create: `scripts/audit_release_tree.py`
- Create: `tests/unit/test_release_tree_audit.py`

- [ ] **Step 1: 写禁止路径和内容的红测试**

```python
TRACKED_PATH_CASES = {
    "reports/run.json": "runtime-report",
    ".review_queue/task.json": "user-review-data",
    ".data_protocol/gold.json": "dataset-entity",
    "training-data/raw/photo.jpg": "training-data-entity",
    "recognition-models/production/model.pt": "model-weight",
    "runtime/platform.sqlite3": "runtime-state",
    "docs/demo/customer.xlsx": "business-data-file",
}
TRACKED_CONTENT_CASES = {
    "TOKEN=ghp_example": "credential-pattern",
    "/Users/zhangweiqi/Documents/QY/项目/LLM-Image": "legacy-absolute-path",
    '\"trace_id\":\"tr-real-example\"': "runtime-evidence",
    '\"created_by\":\"admin\"': "runtime-evidence",
}
```

- [ ] **Step 2: 运行红测试**

Run: `pytest tests/unit/test_release_tree_audit.py -q`

Expected: FAIL，因为 `src.common.release_tree_audit` 尚不存在。

- [ ] **Step 3: 实现审计器和 CLI**

```python
ALLOWED_LOCAL_DOCS = {
    "training-data/README.md",
    "recognition-models/README.md",
    "runtime/README.md",
}
BLOCKED_ROOTS = {
    "reports": "runtime-report",
    ".review_queue": "user-review-data",
    ".data_protocol": "dataset-entity",
    ".datasets_nextgen": "dataset-entity",
    ".micro_gold_v2": "dataset-entity",
    "training-data": "training-data-entity",
    "recognition-models": "model-weight",
    "runtime": "runtime-state",
}
BLOCKED_SUFFIXES = {
    ".pt", ".pth", ".onnx", ".safetensors", ".sqlite", ".sqlite3",
    ".db", ".xlsx", ".xls", ".csv", ".jsonl", ".jpg", ".jpeg", ".png",
}
CONTENT_RULES = (
    ("credential-pattern", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")),
    ("legacy-absolute-path", re.compile(r"/Users/[^/]+/Documents/QY/项目/LLM-Image")),
    ("runtime-evidence", re.compile(r'"(?:trace_id|created_by|file_count)"\\s*:')),
)

@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    detail: str

def blocked_path_rule(path: PurePosixPath) -> str | None:
    raw_path = path.as_posix()
    if raw_path in ALLOWED_LOCAL_DOCS:
        return None
    if path.parts and path.parts[0] in BLOCKED_ROOTS:
        return BLOCKED_ROOTS[path.parts[0]]
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        return "forbidden-binary-or-business-data"
    if "/execution/evidence/" in f"/{raw_path}" or "before-snapshots" in path.parts or "after-snapshots" in path.parts:
        return "runtime-evidence"
    if path.name in {"EXECUTION-LOG.md", "FINAL-REPORT.md", "STATUS.md"} and "implementation" in path.parts:
        return "runtime-evidence"
    return None

def audit_paths(root: Path, tracked_paths: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for raw_path in sorted(set(tracked_paths)):
        path = PurePosixPath(raw_path)
        rule = blocked_path_rule(path)
        if rule:
            findings.append(Finding(raw_path, rule, "tracked path is forbidden"))
            continue
        disk_path = root / path
        is_negative_fixture = raw_path == "tests/unit/test_release_tree_audit.py"
        if not is_negative_fixture and disk_path.is_file() and disk_path.stat().st_size <= 2_000_000:
            text = disk_path.read_text(encoding="utf-8", errors="ignore")
            for content_rule, pattern in CONTENT_RULES:
                if pattern.search(text):
                    findings.append(Finding(raw_path, content_rule, "forbidden tracked content"))
    return findings

def audit_git_tree(root: Path) -> list[Finding]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    tracked = [item.decode("utf-8") for item in completed.stdout.split(b"\\0") if item]
    return audit_paths(root, tracked)

def findings_as_json(findings: Sequence[Finding]) -> str:
    payload = {"ok": not findings, "finding_count": len(findings), "findings": [asdict(item) for item in findings]}
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
```

规则区分可提交的三个 `README.md` 和目录内被禁止的资产实体；只扫描 `git ls-files`，不读取被忽略的本地训练数据。

- [ ] **Step 4: 跑绿测试并提交**

```bash
pytest tests/unit/test_release_tree_audit.py -q
python scripts/audit_release_tree.py --root . --format json
git add src/common/release_tree_audit.py scripts/audit_release_tree.py tests/unit/test_release_tree_audit.py
git commit -m "feat: add clean release tree audit"
```

Expected: 测试 PASS；CLI 在清理前精确报出现有违规文件。

### Task 3: 建立本地资产分区和兼容映射

**Files:**
- Modify: `.gitignore`
- Create: `training-data/README.md`
- Create: `recognition-models/README.md`
- Create: `runtime/README.md`
- Create: `scripts/bootstrap_local_assets.py`
- Create: `tests/unit/test_bootstrap_local_assets.py`

- [ ] **Step 1: 写链接映射红测试**

```python
LEGACY_LINKS = {
    ".models": "recognition-models/registry",
    ".sam_checkpoints": "recognition-models/foundation/sam",
    ".datasets": "training-data/processed/datasets",
    ".datasets_nextgen": "training-data/processed/datasets-nextgen",
    ".training_data": "training-data/processed/training-data",
    ".batch3_clean": "training-data/processed/batch3-clean",
    ".kb": "training-data/processed/knowledge-base",
    ".micro_gold_v1": "training-data/evaluation/micro-gold-v1",
    ".micro_gold_v2": "training-data/evaluation/micro-gold-v2",
    ".data_protocol": "training-data/evaluation/data-protocol",
    ".eval": "training-data/evaluation/legacy-eval",
    ".platform": "runtime/platform",
    ".label-studio": "runtime/label-studio",
}
```

- [ ] **Step 2: 运行红测试**

Run: `pytest tests/unit/test_bootstrap_local_assets.py -q`

Expected: FAIL，bootstrap 脚本尚不存在。

- [ ] **Step 3: 实现幂等 bootstrap 脚本和忽略白名单**

bootstrap 只创建相对符号链接，不覆盖真实文件；支持 `--dry-run` 和 JSON 输出。`.gitignore` 加入：

```gitignore
training-data/**
!training-data/README.md
recognition-models/**
!recognition-models/README.md
runtime/**
!runtime/README.md
```

- [ ] **Step 4: 跑绿测试并提交**

```bash
pytest tests/unit/test_bootstrap_local_assets.py -q
git add .gitignore training-data/README.md recognition-models/README.md runtime/README.md scripts/bootstrap_local_assets.py tests/unit/test_bootstrap_local_assets.py
git commit -m "chore: separate local data model and runtime assets"
```

### Task 4: 将旧本地资产无破坏地归档到新目录

**Files:**
- Local only: `training-data/**`
- Local only: `recognition-models/**`
- Local only: `runtime/**`

- [ ] **Step 1: 用 macOS APFS `cp -cR` 归档训练数据**

```text
原始照片目录与 xlsx                       -> training-data/raw/
.datasets/                                   -> training-data/processed/datasets/
.datasets_nextgen/                           -> training-data/processed/datasets-nextgen/
.training_data/                              -> training-data/processed/training-data/
.batch3_clean/                               -> training-data/processed/batch3-clean/
crop_dataset*/cropped_images/batch3_gray/    -> training-data/processed/
.kb/.labels/.quality/.review_queue/          -> training-data/processed/
.micro_gold*/.data_protocol/.eval/.sam_runs/ -> training-data/evaluation/
reports/                                     -> runtime/legacy-reports/
```

- [ ] **Step 2: 归档识别模型**

```text
.models/             -> recognition-models/registry/
.sam_checkpoints/    -> recognition-models/foundation/sam/
根目录 YOLO *.pt   -> recognition-models/foundation/yolo/
best/                -> recognition-models/candidates/legacy-best/
```

- [ ] **Step 3: 归档运行时状态**

```text
.platform/       -> runtime/platform/
.label-studio/   -> runtime/label-studio/
.warehouse/      -> runtime/warehouse/
.field/          -> runtime/field/
```

不复制 `.env`、`.venv*`、`node_modules`、`__pycache__`、`.pytest_cache`、`.DS_Store`、`.claude`、`.gstack` 和异常 `~/`。

- [ ] **Step 4: 创建兼容链接并校验**

```bash
python scripts/bootstrap_local_assets.py
python -m src.models.bundle verify --bundle-id prod_20260805_v5_r1
git status --short --ignored
```

Expected: 生产 bundle 验证通过；资产实体和链接全部被 Git 忽略。

### Task 5: 清理新 Git 文件树中的用户数据和运行证据

**Files:**
- Remove: `reports/**`, `.review_queue/**`, `.data_protocol/**`, `.micro_gold_v2/**`, `.datasets_nextgen/**`
- Remove: `docs/implementation/**/execution/**`, `**/before-snapshots/**`, `**/after-snapshots/**`
- Remove: operational `EXECUTION-LOG.md`, `FINAL-REPORT.md`, `STATUS.md`
- Modify: `docs/superpowers/specs/2026-08-14-taas-agent-operation-project-extraction-design.md`
- Modify: `docs/superpowers/plans/2026-08-14-taas-agent-operation-project-extraction.md`
- Modify: `web/src/pages/Overview.tsx`
- Remove: `web/public/img/shelf1.jpg`, `shelf2.jpg`, `shelf3.jpg`
- Create: `web/public/img/shelf-demo.svg`

- [ ] **Step 1: 从新分支跟踪树移除现场证据**

只在新克隆中执行 `git rm`；Task 4 的本地忽略归档保留。架构、设计、决策和实施计划文档继续跟踪。
同时将本设计和本计划中的旧工作区绝对路径替换为 `<legacy-workspace>`，将新主目录写为相对路径或 `<project-root>`。

- [ ] **Step 2: 用中性 SVG 替换来源不可证明的货架照片**

`shelf-demo.svg` 不包含品牌、照片或用户信息。`Overview.tsx` 改用 `/img/shelf-demo.svg`，alt 为“货架识别演示占位图”。

- [ ] **Step 3: 运行契约测试和发布树审计**

```bash
pytest tests/promotion/test_three_audience_html.py -q
python scripts/audit_release_tree.py --root . --format json
```

Expected: 测试 PASS；继续清理直到 finding=0。

- [ ] **Step 4: 提交清理结果**

```bash
git add -u
git add .gitignore web/src/pages/Overview.tsx web/public/img/shelf-demo.svg
git commit -m "chore: remove user and runtime data from release tree"
```

### Task 6: 补齐新主目录的开发入口文档

**Files:**
- Modify: `README.md`, `.env.example`
- Create: `docs/PROJECT-STRUCTURE.md`, `docs/LOCAL-ASSETS.md`
- Create: `tests/contract/test_project_structure_docs.py`

- [ ] **Step 1: 写文档契约红测试**

```python
REQUIRED_DOMAINS = {
    "platform-kernel", "graph-loop", "training-control", "dataset-factory",
    "fmcg-recognition", "labeling-review", "model-runtime", "web-workbench",
}
REQUIRED_LOCAL_ZONES = {"training-data", "recognition-models", "runtime"}
```

- [ ] **Step 2: 运行红测试**

Run: `pytest tests/contract/test_project_structure_docs.py -q`

Expected: FAIL，新结构文档尚未创建。

- [ ] **Step 3: 编写开发入口和本地资产恢复指南**

README 列出 Python/Web 安装、asset bootstrap、测试、构建和敏感数据约束。`PROJECT-STRUCTURE.md` 列出 20 个 Python 一级包、29 个 Web 页面业务分组和 4 类测试套件。`LOCAL-ASSETS.md` 不列用户文件名或绝对路径。

- [ ] **Step 4: 跑绿测试并提交**

```bash
pytest tests/contract/test_project_structure_docs.py -q
git add README.md docs/PROJECT-STRUCTURE.md docs/LOCAL-ASSETS.md .env.example tests/contract/test_project_structure_docs.py
git commit -m "docs: document complete system and local asset layout"
```

### Task 7: 运行完整性、测试、构建和数据卫生验证

**Files:**
- Verify: entire repository
- Generated local only: `.venv/`, `web/node_modules/`, `web/dist/`

- [ ] **Step 1: 安装并运行 Python 默认套件**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Expected: pytest 退出码 0，失败数 0。

- [ ] **Step 2: 安装并构建 Web 应用**

```bash
npm --prefix web ci
npm --prefix web run build
```

Expected: Vite/TypeScript 生产构建退出码 0。

- [ ] **Step 3: 运行源码对账和禁止类型扫描**

```bash
comm -23 /tmp/taas-source-files.txt <(git ls-files 'src/**' 'web/**' 'tests/**' 'scripts/**' | sort)
git ls-files | rg '\.(pt|pth|onnx|safetensors|sqlite|sqlite3|db|xlsx|xls|csv|jsonl|jpg|jpeg|png)$'
python scripts/audit_release_tree.py --root . --format json
git diff --check
```

Expected: `comm` 无输出；禁止类型无输出；finding=0；`git diff --check` 通过。

- [ ] **Step 4: 扫描凭据、用户运行证据和绝对路径**

```bash
rg -n --hidden -g '!**/.git/**' -g '!training-data/**' -g '!recognition-models/**' -g '!runtime/**' -g '!web/node_modules/**' -g '!.venv/**' '(gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|/Users/zhangweiqi/Documents/QY/项目/LLM-Image|"trace_id"\s*:|"created_by"\s*:|"file_count"\s*:)' .
```

Expected: 没有经确认的真实凭据、用户运行记录或旧工作区绝对路径。

### Task 8: 从冻结提交做独立克隆验收并推送

**Files:**
- Create: `docs/releases/app-v0.3.0-taas.1.md`
- Tag: `app-v0.3.0-taas.1`
- Remote branch: `origin/codex/taas-agent-operation-v1`

- [ ] **Step 1: 写入冻结版发布记录**

`docs/releases/app-v0.3.0-taas.1.md` 记录基线提交、模块计数、测试结果、Web 构建结果、发布树审计结果、本地资产排除策略和“未合并 main / 未部署 / 未切换生产模型”声明。

- [ ] **Step 2: 生成冻结提交**

```bash
git add docs/releases/app-v0.3.0-taas.1.md
git diff --cached --check
git commit -m "release: freeze clean TaaS agent operation baseline"
```

- [ ] **Step 3: 从 HEAD 创建无本地资产的临时克隆**

```bash
VERIFY_DIR=$(mktemp -d /tmp/taas-clean-verify.XXXXXX)
git clone --no-local --branch codex/taas-agent-operation-v1 . "$VERIFY_DIR/repo"
git -C "$VERIFY_DIR/repo" status --short
python "$VERIFY_DIR/repo/scripts/audit_release_tree.py" --root "$VERIFY_DIR/repo" --format json
```

Expected: 临时克隆工作树为空，finding=0。

- [ ] **Step 4: 推送分支和注释标签**

```bash
git push -u origin codex/taas-agent-operation-v1
git tag -a app-v0.3.0-taas.1 -m 'Clean TaaS by Agent Operation development baseline'
git push origin app-v0.3.0-taas.1
```

- [ ] **Step 5: 最终远端对账**

```bash
test "$(git rev-parse HEAD)" = "$(git ls-remote origin refs/heads/codex/taas-agent-operation-v1 | awk '{print $1}')"
test "$(git rev-parse HEAD)" = "$(git rev-list -n 1 app-v0.3.0-taas.1)"
git status --short --branch
```

Expected: 分支和标签指向同一冻结提交，本地与远端同步，无可提交脏文件。

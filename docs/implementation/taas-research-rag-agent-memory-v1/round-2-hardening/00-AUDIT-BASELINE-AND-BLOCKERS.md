# Round 2 现场基线与阻断项

## 1. 权威现场事实

本页记录 2026-08-21 fresh 复核结果。执行 Agent 开始下一轮时必须重新生成自己的基线，不能直接复制这些数字。

| 项目 | Fresh 结果 |
|---|---|
| 开发目录 | `/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation` |
| Branch / HEAD | `codex/taas-agent-operation-v1` / `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610` |
| 工作树 | 8 个 tracked 修改，大量 cognition/governance/research/docs/frontend 新文件未跟踪；均未 commit |
| 后端 hermetic | `2034 passed, 6 skipped, 6 deselected, 0 failed`，约 311 秒 |
| 前端 | lint clean；2 个 test file、16 tests passed；Vite build 成功 |
| Research eval | exit 1；paraphrase recall、abstention、citation 三项不通过 |
| live SQLite | `runtime/platform/platform.sqlite`，SHA-256 `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109` |
| live migration | 68，最新 `068_cognition_research_report_v1` |
| 061 备份 | `runtime/platform/backups/platform_pre_cognition_20260820T144949Z.sqlite`，SHA-256 `aef8f09670bbce738f81b15ab49144cf9b5bc686074525f8e517446e2ea4c38e`，integrity ok |
| 新认知/研究表 | 现场均为 0 行 |

Fresh 命令：

```bash
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -p no:cacheprovider -q

npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build

PYTHONPATH=src .venv/bin/python scripts/eval_research_rag.py \
  --suite v1 --frozen
```

评测失败项：

```text
paraphrase.recall_at_10 = 0.0      threshold >= 0.90
citation.precision      = unmeasured
abstention_accuracy     = 0.833333 threshold >= 0.90
```

## 2. P0 阻断项

### R2-P0-01 迁移守卫晚于自动 schema migration

`scripts/cognition_migrate_legacy.py` 的 `--apply` 分支先构造 `PlatformStore`。`PlatformStore.__init__` 会设置 WAL 并立即调用 `apply_migrations()`，备份校验却在后续 `run_migration()` 才发生。

使用 061 备份副本、把备份目录指向不存在位置的复现结果：

```text
before                 = (61, 61)
after_store_init       = (68, 68)
guard_error            = MigrationNotAuthorized
after_guard_rejection  = (68, 68)
```

结论：备份守卫只能阻止 legacy row 搬运，不能阻止 schema 先修改数据库。G10 迁移安全不成立。

### R2-P0-02 Research API 的 run scope 未授权

`POST /research/runs` 没有建立经过 IAM 校验的 customer/project scope。status/resume/cancel/decide-conflict/claims 只要求登录，然后按 run ID 访问。citations/synthesize 接受调用者提供的 customer/project 参数，但不与 run 固化 scope 对账。

结论：任意已登录主体在获得 run ID 后可能跨授权范围读取或改变研究任务。G9 安全门不成立。

## 3. P1 阻断项

### R2-P1-01 Research Graph 仍是骨架

- Planner 固定生成一个原问题，不做子问题分解。
- gap search 只追加“补充 证据”。
- 没有独立 counterevidence 节点。
- 命中两个来源即判为冲突，没有判断证据关系。

预算、checkpoint 和 resume 已存在，但 G7 要求的研究行为未完整落地。

### R2-P1-02 Citation Gate 没有验证支持关系

当前 Claim 只要有 span 就写 `supports + verifier_score=1.0`。Verifier 校验 span 存在、来源状态、ACL、时间和 scope，但不判断 span 是否蕴含 Claim。评测也没有真实 claim/citation 样本。

### R2-P1-03 finalize 可以留下假成功

Evidence bundle 创建和 Business Run 状态同步异常被吞掉，Research Run 仍可写为 succeeded。这会破坏 Research/BusinessRun/Evidence 三者的终态一致性。

### R2-P1-04 dense provider 与索引身份不完整

当前运行环境没有 `sentence-transformers`、`transformers`、`onnxruntime`、`fastembed` 或 MLX embedding 包。`openai` 当前环境已安装，但没有形成项目依赖和受控 embedding 配置。

索引 ID 没有包含 provider/model/dimension/parameters；API build 也没有传 provider。已有 lexical build 可能被错误复用，无法可靠升级为 dense/hybrid。

### R2-P1-05 固定评测不是设计要求的完整评测

当前 gold set 只覆盖 exact、paraphrase、insufficient 和 ACL；temporal、multi-hop、global、conflict、Skill、L2、L3 尚未覆盖。citation、reader、research、latency 和成本指标没有形成发布证据。

### R2-P1-06 API/UI 系统验收未闭环

现有 API 测试覆盖登录、CSRF、单用户流程和少量搜索，但没有跨主体/客户/项目访问、并发 resume/cancel、rate limit、idempotency key 和 run scope 负例。前端只有通用单元测试，没有 Research Workbench 浏览器验收。

## 4. Gate 重新判定

| Gate | 判定 | 说明 |
|---|---|---|
| G0 | PARTIAL | DB integrity 和回归正常；历史现场快照已过期 |
| G1 | PASS | Context/schema/hash/fail-closed 合同通过 |
| G2 | PASS | Policy/approval/alert/pause 机器合同通过 |
| G3 | PASS | immutable source→span 和注入隔离通过 |
| G4 | PARTIAL | L1/L2/L3 生命周期通过；迁移 CLI 安全失败 |
| G5 | PASS | Knowledge/Skill 生命周期机器合同通过 |
| G6 | FAIL | ACL 负例通过；语义 recall 与延迟门不通过/未测量 |
| G7 | FAIL | budget/resume 通过；plan/gap/counterevidence/conflict 语义不完整 |
| G8 | FAIL | span 结构校验存在；支持性和 citation precision 未验证 |
| G9 | FAIL | Research API scope P0；浏览器/性能/系统恢复证据缺失 |
| G10 | NOT_STARTED | 前置 Gate 未通过，尚不能开始正式验收 |

## 5. 正确状态

Round 1 的准确表述应为：Task 1–7 的主要机器框架落地；Task 8–13 仍需 Round 2 收口。当前总状态必须是：

```text
BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION
```

禁止使用“Task 1–13 全部完成”“G0–G9 全绿”或 `READY_FOR_UAT`，直到本目录的所有机器 Gate 重新通过。

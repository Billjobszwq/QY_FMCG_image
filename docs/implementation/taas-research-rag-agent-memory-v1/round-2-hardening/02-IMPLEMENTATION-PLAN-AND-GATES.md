# TaaS Research RAG Round 2 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` only when the user explicitly authorizes subagents; otherwise use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Round 1 已确认的迁移、授权、终态一致性、dense/hybrid、Research Graph、Citation、评测和系统验收缺口，使 G0–G9 具备 fresh、可复核的机器证据。

**Architecture:** 保留现有 cognition bounded context 和已通过合同，先建立迁移只读预检与 Research scope authorization，再修正 Research UoW 终态；随后接入真实 vector provider、扩展显式研究节点和 Claim 支持性验证，最后补齐金标准、浏览器、性能、恢复与文档状态。任何 provider 或真实 UAT 外部条件缺失时 fail-closed。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLite、现有 IAM/Scope/Run/Evidence/Usage、React/TypeScript、Pytest、可选 OpenAI-compatible 或本地 embedding provider。

---

## 0. 执行纪律

- 顺序执行 R2-01 → R2-10；P0 未通过时不得开始语义或 UI 收口。
- 每个行为变化必须先见红，再做最小实现，再跑目标与相邻回归。
- 不改写 001–068 历史迁移；新增 schema 只能使用 069 以后编号且纯追加。
- 所有 DB 破坏性验证只使用 `mktemp -d` 下的显式副本；不删除副本，记录路径。
- 不修改 live 数据内容，不回滚 live 068，不删除用户文件，不启动训练或生产切换。
- 未获明确 commit 授权时跳过 commit；不得因跳过 commit 阻断下一 Task。
- 每个 Task 更新 `STATUS.md`、`ISSUES.md`、`DECISIONS.md`、`EXECUTION-LOG.md`，但只写 fresh 事实。

## 1. 文件责任图

### 新建

```text
src/platform/api/cognition_auth.py               # IAM + ScopeResolver + CognitiveContext 唯一 API 构造器
src/platform/cognition/index/providers.py        # 真实 vector provider adapter 与配置
src/platform/cognition/research/planner.py        # typed subquestion plan
src/platform/cognition/research/reader.py         # span evidence extraction
src/platform/cognition/research/critic.py         # sufficiency/gap/conflict/counterevidence decision
src/platform/cognition/research/claims.py         # claim build 与 support verification ports
tests/cognition/test_migration_preflight_cli.py
tests/cognition/test_vector_provider_integration.py
tests/research/test_research_scope_authorization.py
tests/research/test_research_concurrency.py
tests/research/test_research_terminal_integrity.py
tests/research/test_research_planner_counterevidence.py
tests/research/test_claim_support_semantics.py
tests/research/test_release_eval_coverage.py
frontend/src/pages/research/Workbench.test.tsx
frontend/playwright.config.ts
frontend/e2e/research-workbench.spec.ts
```

### 修改

```text
scripts/cognition_migrate_legacy.py
src/platform/iam.py
src/platform/cognition/context.py
src/platform/api/cognition_api.py
src/platform/api/research_api.py
src/platform/cognition/composition.py
src/platform/cognition/index/vector.py
src/platform/cognition/index/catalog.py
src/platform/cognition/index/gateway.py
src/platform/cognition/research/graph.py
src/platform/cognition/research/service.py
src/platform/cognition/research/citations.py
src/platform/cognition/research/synthesizer.py
src/platform/cognition/evaluation/dataset.py
src/platform/cognition/evaluation/retrieval.py
src/platform/cognition/evaluation/citations.py
src/platform/cognition/evaluation/harness.py
src/platform/cognition/evaluation/report.py
scripts/eval_research_rag.py
scripts/reconcile_cognition.py
tests/fixtures/cognition/gold_queries.jsonl
frontend/src/lib/api.ts
frontend/src/pages/research/Workbench.tsx
```

## R2-01：冻结 Round 2 基线和证据格式

**Files:**

- Modify: `scripts/audit_cognition_baseline.py`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/STATUS.md`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/ISSUES.md`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/DECISIONS.md`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/EXECUTION-LOG.md`

- [ ] **Step 1: 记录现状而不触发可写 Store**

  使用 SQLite `mode=ro` 读取 integrity、migration、table counts，并记录 live DB SHA、size、mtime。记录 branch/HEAD/status、provider availability、训练进程和 production bundle。

- [ ] **Step 2: 把状态改为阻断态**

  将总体状态写为 `BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION`。Task 8–13 改为 `IN_PROGRESS` 或 `BLOCKED`，不得保留“全部 DONE”。

- [ ] **Step 3: 修正文档账本**

  将已经由实现取代的 ISS-001…ISS-008 标记 `SUPERSEDED` 或 `CLOSED_WITH_EVIDENCE`，新增本目录 R2-P0/P1；修复重复 Decision ID；旧 `READY_FOR_UAT` 记录保留但明确标为后续证据推翻。

- [ ] **Step 4: 验证基线**

  Run:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/audit_cognition_baseline.py
  git diff --check
  ```

  Expected: 脚本不改变 live DB hash；文档状态与现场一致。

## R2-02：修复迁移预检顺序

**Files:**

- Modify: `scripts/cognition_migrate_legacy.py`
- Create: `tests/cognition/test_migration_preflight_cli.py`
- Modify: `tests/cognition/test_memory_legacy_migration.py`

- [ ] **Step 1: 写 CLI 失败路径红测试**

  从 061 备份复制到 `tmp_path/pre.sqlite`，记录 bytes/hash/migration count；以不存在备份目录执行 `main --apply --yes-i-have-backup --db pre.sqlite`，断言 exit 2 且全部记录不变。

  ```python
  def test_apply_guard_runs_before_store_and_schema_migrations(tmp_path):
      db = copy_pre_062_database(tmp_path)
      before = database_fingerprint(db)
      result = run_cli(db, backup_dir=tmp_path / "missing", apply=True)
      assert result.returncode == 2
      assert database_fingerprint(db) == before
  ```

- [ ] **Step 2: 运行红测试**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest -q \
    tests/cognition/test_migration_preflight_cli.py -x
  ```

  Expected: FAIL，migration count 从 61 变 68。

- [ ] **Step 3: 实现 readonly preflight**

  把 backup/integrity/hash 检查提到独立函数；preflight 只用 `sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)`。只有 preflight pass 后才构造 `PlatformStore`。

- [ ] **Step 4: 补齐 dry-run、有效备份和幂等测试**

  断言 dry-run 不生成 WAL/SHM；有效备份后 apply 到 68；两次 legacy apply 第二次 migrated=0；旧表行数/hash 不变；L3/L4 映射不丢失。

- [ ] **Step 5: 回归**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest -q \
    tests/cognition/test_migration_preflight_cli.py \
    tests/cognition/test_memory_legacy_migration.py \
    tests/platform/test_platform_store.py
  ```

  Expected: PASS；所有 DB 都是临时副本。

## R2-03：Research API IAM、scope 与并发控制

**Files:**

- Create: `src/platform/api/cognition_auth.py`
- Modify: `src/platform/iam.py`
- Modify: `src/platform/cognition/context.py`
- Modify: `src/platform/api/cognition_api.py`
- Modify: `src/platform/api/research_api.py`
- Modify: `src/platform/cognition/research/service.py`
- Create: `tests/research/test_research_scope_authorization.py`
- Create: `tests/research/test_research_concurrency.py`

- [ ] **Step 1: 写跨主体/客户/项目红测试**

  建立 cust-a/project-a 与 cust-b/project-b 两组 IAM membership。A 创建 run 后，B 对 status/claims/citations/synthesize/resume/cancel/decide 全部得到安全拒绝；无权响应不得包含 question、state、counts 或 scope。

- [ ] **Step 2: 写 start scope 红测试**

  请求未知 customer/project、fixture customer 无 test_run、无 `research.run` permission 必须拒绝；平台管理员例外由 IAM 明确授权，不由 role 字符串硬编码。

- [ ] **Step 3: 增加权限 bundle 和共享 Context 工厂**

  增加 `cognition.read/manage`、`research.read/run/decide`；`cognition_auth.py` 统一执行 session → IAM → ScopeResolver → `context_from_scope`。删除 cognition/research API 内手写 `_ctx()`。

- [ ] **Step 4: 让所有 service 操作接收 Context**

  `get_run/list_claims/list_queries/resume/cancel/decide_conflict` 全部要求 `ctx` 和 permission；citations/synthesize 从 run scope 派生 verifier context，禁止 query 参数覆盖。

- [ ] **Step 5: 写并发红测试并实现 CAS**

  两个线程/连接同时 resume、resume+cancel、双 decide，只允许一个状态转换成功；另一个返回 `CognitionConflictError`，不产生重复 step/query/usage/claim。

- [ ] **Step 6: API 回归**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest -q \
    tests/research/test_research_scope_authorization.py \
    tests/research/test_research_concurrency.py \
    tests/research/test_research_api.py \
    tests/platform/test_abos_v2_iam_master.py \
    tests/platform/test_si3_scope_integrity.py
  ```

  Expected: 所有跨 scope 负例为零泄漏；既有 auth/CSRF 流程通过。

## R2-04：Research 终态 UoW 与错误诚实性

**Files:**

- Modify: `src/platform/cognition/repository.py`
- Modify: `src/platform/cognition/research/service.py`
- Modify: `src/platform/cognition/research/synthesizer.py`
- Create: `tests/research/test_research_terminal_integrity.py`

- [ ] **Step 1: 写 Evidence/BusinessRun 故障注入红测试**

  分别让 evidence insert、business status、work status、event/outbox 写入失败；断言 research run 不为 succeeded，且不会返回成功报告 ID。

- [ ] **Step 2: 实现 ResearchUnitOfWork**

  将 report/evidence/research/business/work/event 终态写入同一显式事务。移除 `_stop/_finalize` 的宽泛吞异常；错误映射到稳定类型和 stop reason。

- [ ] **Step 3: 加终态对账**

  `scripts/reconcile_cognition.py` 报告 succeeded research 缺 report/evidence、research/business/work 状态漂移、孤儿 step/query/claim；任一项使 G9 fail。

- [ ] **Step 4: 回归**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest -q \
    tests/research/test_research_terminal_integrity.py \
    tests/research/test_research_graph.py \
    tests/research/test_research_resume_budget.py
  ```

## R2-05：真实 Vector Provider 与不可混淆索引身份

**Files:**

- Modify: `pyproject.toml`
- Modify: `src/platform/cognition/index/vector.py`
- Create: `src/platform/cognition/index/providers.py`
- Modify: `src/platform/cognition/index/catalog.py`
- Modify: `src/platform/cognition/index/gateway.py`
- Modify: `src/platform/cognition/composition.py`
- Modify: `src/platform/api/cognition_api.py`
- Create: `tests/cognition/test_vector_provider_integration.py`

- [ ] **Step 1: 写索引 identity 红测试**

  同 corpus 的 lexical、provider-a/model-1、provider-a/model-2、不同 dimension 和 parameters 必须得到不同 snapshot ID；旧 lexical build 不得被 dense build 复用。

- [ ] **Step 2: 写 provider mismatch 红测试**

  build provider/model 与 query provider/model 不一致时不计算 cosine，不返回看似正常的 hybrid；结果明确 degraded/provider_mismatch。

- [ ] **Step 3: 实现受控 provider adapter**

  首选 OpenAI-compatible adapter：endpoint/model/key 只从配置读取，key 不进入日志、artifact 或 hash；加入可选依赖。若用户已批准本地模型，再加 local adapter；hermetic 测试只用注入的 deterministic fake 验证协议，不声称质量达标。

- [ ] **Step 4: 贯通 composition/API/build/activate**

  组合根创建同一 provider 实例供 build 和 query；build API 不接受任意 endpoint/key；artifact 保存完整 provider identity、vector count 和参数；activate 校验质量与 identity。

- [ ] **Step 5: 真实 provider 评测**

  ```bash
  PYTHONPATH=src .venv/bin/python scripts/eval_research_rag.py \
    --suite v1 --frozen --retrieval hybrid \
    --out runtime/platform/evidence/cognition-r2-eval.json
  ```

  Expected: 使用真实 provider 时 `paraphrase.recall_at_10 >= 0.90`。若 provider 不可用，命令必须失败并写 `BLOCKED_BY_EMBEDDING_PROVIDER`，不得用 fake 结果放行。

## R2-06：显式 Research Planner、Gap 与 Counterevidence

**Files:**

- Create: `src/platform/cognition/research/planner.py`
- Create: `src/platform/cognition/research/reader.py`
- Create: `src/platform/cognition/research/critic.py`
- Modify: `src/platform/cognition/research/graph.py`
- Modify: `src/platform/cognition/research/service.py`
- Create: `tests/research/test_research_planner_counterevidence.py`

- [ ] **Step 1: 写节点 schema 和路径红测试**

  deep_research 产生多个有依赖的子问题、每个带停止条件；gap 与 counterevidence 是独立 step；lookup 保持最小路径。

- [ ] **Step 2: 写真实冲突红测试**

  两个一致来源不得 waiting_human；相同命题出现互斥数值/否定关系才进入 counterevidence，无法裁决时 waiting_human。

- [ ] **Step 3: 实现 typed planner/reader/critic**

  provider 输出必须经过 Pydantic schema、budget 和 scope 校验。provider 不可用时 lookup 可走确定性最小路径；deep_research 必须 degraded/abstain，不能伪装完整规划。

- [ ] **Step 4: 实现 novelty 与停止条件**

  query key 绑定 run/subquestion/action/iteration；连续两轮没有新有效 span 停止；counterevidence query 必须避免把期望结论写成事实前提。

- [ ] **Step 5: 恢复回归**

  对新增每个节点注入故障，resume 不重复 query/usage/claim，不切换 snapshot。

## R2-07：Claim 支持性验证与 Citation Gate

**Files:**

- Create: `src/platform/cognition/research/claims.py`
- Modify: `src/platform/cognition/research/citations.py`
- Modify: `src/platform/cognition/research/synthesizer.py`
- Modify: `src/platform/cognition/evaluation/citations.py`
- Create: `tests/research/test_claim_support_semantics.py`

- [ ] **Step 1: 写伪引用红测试**

  span 存在但讨论不同主体、数值、时间、否定方向或只提供背景时，高重要性 Claim 必须 fail。URL/locator 存在不等于 supports。

- [ ] **Step 2: 移除自动满分**

  ClaimBuilder 初始关系为 unverified，不写 `verifier_score=1.0`。Verifier 保存 verifier id/version、input hash、relation、score、reason 和时间。

- [ ] **Step 3: 实现两层 verifier**

  先做确定性 source/scope/time/number/entity checks，再调用结构化 support provider。provider 不可用时高重要性 Claim 返回 research_more/remove。

- [ ] **Step 4: 评测基于 gold label**

  citation precision/recall 使用人工 fixture 的 expected relation 计算；不能用系统自己写入的 relation 当标签。

- [ ] **Step 5: 回归**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest -q \
    tests/research/test_claim_support_semantics.py \
    tests/research/test_claim_citation_gate.py \
    tests/research/test_contradiction_abstention.py
  ```

## R2-08：补齐固定金标准和发布 Gate

**Files:**

- Modify: `tests/fixtures/cognition/gold_queries.jsonl`
- Create: `tests/fixtures/cognition/gold_claim_citations.jsonl`
- Create: `tests/fixtures/cognition/corpus/policy_versions.md`
- Create: `tests/fixtures/cognition/corpus/multi_hop_org.md`
- Create: `tests/fixtures/cognition/corpus/conflict_policy_a.md`
- Create: `tests/fixtures/cognition/corpus/conflict_policy_b.md`
- Create: `tests/fixtures/cognition/l2_cases.jsonl`
- Create: `tests/fixtures/cognition/l3_methods.jsonl`
- Create: `tests/fixtures/cognition/skills.jsonl`
- Modify: `src/platform/cognition/evaluation/dataset.py`
- Modify: `src/platform/cognition/evaluation/harness.py`
- Modify: `src/platform/cognition/evaluation/report.py`
- Modify: `scripts/eval_research_rag.py`
- Create: `tests/research/test_release_eval_coverage.py`

- [ ] **Step 1: 写 coverage 红测试**

  断言 12 个必需 class 每类均有正/负样本，并包含 scope、as_of、expected span/claim、forbidden sources；缺一类直接 fail。

- [ ] **Step 2: 增加分层指标**

  Reader、Citation、Research、System 指标不得用默认 1.0；无样本为 unmeasured 且 Gate fail。记录 p50/p95、resume checkpoints、provider/model/index、cost 和 freshness。

- [ ] **Step 3: 防评测污染**

  provider adapter 不得读取 gold 文件；gold hash 写入报告；样本 ID 去重；fixture 缺失、非法 class、snapshot drift 全部 fail-closed。

- [ ] **Step 4: 运行完整发布评测**

  ```bash
  PYTHONPATH=src .venv/bin/python scripts/eval_research_rag.py \
    --suite v1-release --frozen \
    --out runtime/platform/evidence/cognition-r2-release-eval.json
  ```

  Expected: 所有阈值逐项 pass，`all_gates_pass=true`，报告 hash 可重算；否则状态保持 BLOCKED。

## R2-09：API/UI、浏览器、性能和恢复验收

**Files:**

- Modify: `src/platform/api/research_api.py`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/research/Workbench.tsx`
- Create: `frontend/src/pages/research/Workbench.test.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/research-workbench.spec.ts`

- [ ] **Step 1: API 行为门**

  为 start/resume/cancel/decide/synthesize 增加 rate limit 和 idempotency；验证 401/403/404/409/429、重复请求、跨 scope 和并发。

- [ ] **Step 2: UI 状态门**

  展示 scope、provider/degraded、预算、节点、停止原因、subquestions、counterevidence、Claim verdict、unknown 和 locator；禁用无权动作；不显示 chain-of-thought。

- [ ] **Step 3: 浏览器验收**

  使用 Playwright 场景固定 1024/1280/1440、键盘焦点、空/错/加载、
  waiting_human、resume/cancel、citation block 和跨 scope 无泄漏；随后再用
  `gstack qa-only` 做独立 report-only 复核。浏览器证据写入现有 Gate 约定的
  evidence 目录，不提交截图中的真实用户内容。

- [ ] **Step 4: 性能和恢复**

  固定本地 lookup corpus 测 p50/p95；每个 Research checkpoint 注入一次恢复；SQLite 副本执行备份恢复与 reconcile。不得对 live DB 做恢复演练。

- [ ] **Step 5: 前端和 API 回归**

  ```bash
  npm --prefix frontend run lint
  npm --prefix frontend run test
  npm --prefix frontend run build
  PYTHONPATH=src .venv/bin/python -m pytest -q tests/research/test_research_api.py
  ```

## R2-10：全量验证、独立复审和状态收口

**Files:**

- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/STATUS.md`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/ISSUES.md`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/DECISIONS.md`
- Modify: `docs/implementation/taas-research-rag-agent-memory-v1/EXECUTION-LOG.md`
- Create only after machine gates pass: `docs/implementation/taas-research-rag-agent-memory-v1/READY-FOR-UAT.md`

- [ ] **Step 1: fresh 全量验证**

  ```bash
  XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python -m pytest -p no:cacheprovider -q
  npm --prefix frontend run lint
  npm --prefix frontend run test
  npm --prefix frontend run build
  PYTHONPATH=src .venv/bin/python scripts/eval_research_rag.py \
    --suite v1-release --frozen \
    --out runtime/platform/evidence/cognition-r2-release-eval.json
  PYTHONPATH=src .venv/bin/python scripts/reconcile_cognition.py \
    --read-only --json
  git diff --check
  ```

- [ ] **Step 2: 复核保护边界**

  检查未删除文件、未切 production、无训练进程、无密钥进入 diff、runtime/model/data 未 stage；记录 DB hash/migration/integrity 和所有 evidence artifact hash。

- [ ] **Step 3: 安全与代码复审**

  使用 `gstack review` 和 `gstack cso` 做 report-only 复审；任何 P0/P1 未关闭都返回对应 BLOCKED 状态。浏览器先使用 `gstack qa-only`，不得自动改生产数据。

- [ ] **Step 4: 状态机更新**

  只有 G0–G9 全部 fresh pass 才创建 `READY-FOR-UAT.md`。人工 UAT 前不创建 `FINAL-REPORT.md`，不写 `ACCEPTED`。

## 2. Round 2 Gate

| Gate | 放行条件 |
|---|---|
| R2-G0 Evidence | 当前 HEAD/diff/DB/provider/processes 与证据 hash fresh |
| R2-G1 Migration | 失败 preflight 对 DB 零字节变化；有效备份副本迁移/恢复/对账通过 |
| R2-G2 Authorization | 所有 Research endpoint 跨 principal/customer/project/test scope 零泄漏 |
| R2-G3 Integrity | 无 Research/BusinessRun/Work/Evidence 假成功或终态漂移 |
| R2-G4 Retrieval | 真实 dense/hybrid identity 正确；语义 recall 与 p95 达标；ACL=0 |
| R2-G5 Research | plan/gap/counterevidence/conflict/budget/resume 全部通过 |
| R2-G6 Citation | gold citation precision ≥0.95；高重要性 recall ≥0.98；unsupported=0 |
| R2-G7 Evaluation | 12 类完整、分层指标全测量、hash/freshness 可重算 |
| R2-G8 System | API rate/idempotency、UI、浏览器、性能、恢复、reconcile 通过 |
| R2-G9 Ready | 全量回归、review、CSO、qa-only 无未关闭 P0/P1 |
| R2-G10 UAT | 用户用真实授权数据验收并明确批准 |

## 3. 一次性完成原则

执行 Agent 应连续完成所有不需要新增权限的 Task，不在每个小步骤向用户请求确认。只有以下情况暂停：

- 需要安装/下载本地 embedding 模型或使用新的远端 provider/凭据；
- 需要修改 live 数据、删除文件、commit/push/merge/deploy；
- 需要真实用户 UAT 或扩大现有 scope；
- 同一阻断连续复现三次且已穷尽安全替代路径。

暂停时必须保留测试、日志和 artifact，给出精确 blocker；不能把未完成改写成 DONE。

# ISSUES — TaaS Research RAG & Agent Memory V1

> 状态：OPEN / MITIGATED / CLOSED_WITH_EVIDENCE / SUPERSEDED。
> 只登记 fresh 复核确认的问题；设计文档中的结论必须经本轮现场验证后才登记。

## 结构差距（与设计 00-LIVE-AUDIT-AND-GAP 对应，2026-08-20 fresh 确认）

### ISS-001（P0）双 Agent 事实源：Manifest 与 Definition 分叉 — CLOSED_WITH_EVIDENCE

- 证据：`src/platform/agents/kernel.py _BUILTIN` 声明 12 个 Manifest；
  `src/platform/agents/runtime.py _SEVEN_AGENTS` 只 seed 7 个 Definition；
  现场 DB `agent_manifest_v1=0`、`agent_definition_v1=7`（均 v1 published）。
  Manifest 仅在 `AgentRegistry` 实例化时惰性 seed，当前 DB 未被 seed。
- 影响：Rules/Silent/Knowledge/Research 新角色加入任一入口都会在另一入口漂移。
- 修复方向：Task 3（AgentDefinitionVersion 唯一事实源 + Manifest 只读投影）。
- 关闭证据：`tests/governance/test_agent_definition_projection.py`；Manifest 已改为
  published/declared Definition 的投影。Round 2 仍需在全量回归中保持该合同。

### ISS-002（P0）双记忆表且层级语义冲突 — MITIGATED

- 证据：`memory_entry_v1`（MemoryService，level/scope/acl/confidence/validity）与
  `agent_memory_v1`（AgentRuntime.remember，允许 L0-L4）并存；两表现场均 0 行。
  完整规范要求 L1/L2/L3 且 L2/L3 受治理。
- 修复方向：Task 6（新规范 L1/L2/L3 + 旧表只读适配；两表空，先立契约再导入）。
- 当前结论：新 L1/L2/L3 生命周期和 legacy 只读适配已落地；物理旧表仍保留，
  Stage A–D 切读和迁移入口安全尚未完成，转由 ISS-014 跟踪。

### ISS-003（P0）检索权限不是查询前置条件 — MITIGATED

- 证据：`runtime.py` 的 `kb.search` 对全部 `agent_asset_v1(kind='kb',status='published')`
  做双向子串匹配 top-5，无 customer/permission/effective-time/scope 过滤，
  无 BM25/dense/rerank/span 定位。
- 修复方向：Task 8（CognitiveContext 前置过滤 + 联邦混合检索）。
- 当前结论：新 `CognitiveQueryGateway` 已有 ACL/effective/status pre-filter 负例；
  Research API 进入网关前的 run scope 授权仍缺失，转由 ISS-015 跟踪。

### ISS-004（P0）三个不同含义的 “KB” 并存 — MITIGATED

- 证据：`.kb/`（SKU 识别向量，symlink→training-data/processed/knowledge-base）、
  `knowledge_document_v1`（Import Center 元数据，0 行）、
  `agent_asset_v1(kind='kb')`（Runtime 资产，0 行）。无统一 source/version/chunk/span。
- 修复方向：Task 5/7（source→document→version→chunk→span 链；旧入口只读兼容）。
- 当前结论：新 source→span 和 Knowledge 生命周期已落地；旧入口保留兼容，
  尚未完成正式切读和真实数据 UAT。

### ISS-005（P0）治理角色不在可执行控制链 — CLOSED_WITH_EVIDENCE

- 证据：无 Rules/Silent/Knowledge/Research Agent 的 Runtime Definition；
  无 policy/approval/alert/pause 事实表（迁移止于 061）。
- 修复方向：Task 4（deterministic Policy Decision Point + alert/pause 账本）。
- 关闭证据：`tests/governance/test_policy_alert_pause.py` 覆盖 draft/approval、
  maker≠checker、alert/pause 和 CAS；后续 API action permission 见 ISS-015。

### ISS-006（P1）Evidence 只到 bundle，未到 Claim/span — MITIGATED

- 证据：`evidence_bundle_v1` 无 claim/span 关系表；现场 0 行。
- 修复方向：Task 10（claim_evidence/evidence_span + citation gate）。
- 当前结论：Claim/span 关系表和结构 Gate 已存在；支持性未验证，转 ISS-017。

### ISS-007（P1）Supervisor 双运行路径 — OPEN

- 证据：`supervisor.py SupervisorAgent`（关键词 + DeepSeek 兜底）与
  `runtime.py AgentRuntime`（工具循环）并存；`agent_runtime_api.chat`
  在 runtime 工具循环未命中时回退 SupervisorAgent。
- 修复方向：Task 3/4 收敛到统一 AgentRuntime 后退役 SupervisorAgent。

### ISS-008（P1）服务层直接使用 `store._conn` — OPEN

- 证据：kernel/runtime/blackboard/workflow/import_center/scope 均直接执行 SQL。
- 约束：新 cognition 代码禁止直接 `_conn`，必须 Repository/UoW；旧代码不强制重写。

## 环境与运行观察（本轮 fresh）

### ISS-009 会话默认落在陈旧 worktree — MITIGATED

- 证据：会话 cwd 为 `.claude/worktrees/keen-napier-9a2d19`（branch
  `claude/keen-napier-9a2d19` @ `3f13fa6b`），缺少 frontend/web/runtime/
  training-data 等主仓库内容；主仓库在 `codex/taas-agent-operation-v1` @ `5bbbf898`。
- 处置：全部操作使用主仓库绝对路径（DEC-001）；不写、不删该 worktree。

### ISS-010 `.superpowers/` 在迁移仓库不存在 — OPEN（仅登记）

- 证据：2026-08-20 `find . -maxdepth 2 -name .superpowers` 无结果；
  旧手册把它列为受保护未跟踪目录。
- 处置：基线锁定测试必须容忍“不存在”，但若出现则禁止进入 stage。

### ISS-011 测试环境 LLM provider 环境泄漏风险 — OPEN（已有缓解先例）

- 证据：`src/common/config.py` 导入时把 `.env`（含 DEEPSEEK_API_KEY）灌入
  os.environ；`tests/platform/test_abos_v3_agent_runtime.py` RC-9 已记录
  hermetic 间歇失败模式。新 cognition/research 测试必须显式隔离 provider 环境。

### ISS-012 本机有常驻服务进程（非本轮启动） — OPEN（仅登记）

- 证据：orchestrator :8304、label-studio :8300、training monitor :8092 正在运行；
  平台 API :8400 与 frontend :4173 未运行；无训练进程标记。
- 处置：本轮不启停任何服务；后续 API/UI 联调前 fresh 复核。

### ISS-013 词法基线不通过语义召回 gate（需真实 embedding） — OPEN（已知局限）

- 证据：`scripts/eval_research_rag.py --suite v1 --frozen` 如实报告
  `paraphrase.recall_at_10=0.0 < 0.9`（词法 CJK bigram 与改写句无 token
  交集）、`abstention_accuracy=0.833 < 0.9`（paraphrase 错误 abstain 拉低）、
  `citation.precision` 未度量（V1 仅检索评测）。gate 以 exit 1 如实报告。
- 根因：V1 无离线真实 embedding provider。`index/vector.py` 已有
  VectorProvider 端口 + UnavailableVectorProvider 降级；gateway 已支持
  vector leg（provider 可用则走 hybrid，否则 degraded 词法）。词法基线
  本身无语义理解，paraphrase 必须靠 dense/hybrid。
- 处置：接入真实 embedding provider（本机模型或远端）后复跑评测；
  在此之前语义 gate 保持 FAIL 是**诚实状态**，不得为过门伪造向量或
  放宽阈值。此局限已在 STATUS/EXECUTION-LOG E-22 记录。

### ISS-014 `PYTHONPATH=src` 使 src/platform 遮蔽 stdlib `platform` — OPEN（已知陷阱）

- 证据：`PYTHONPATH=src .venv/bin/python -c "import platform"` 解析到
  `src/platform/__init__.py`（无 `python_version`）；pytest 在 `-v`/
  无 `-p no:cacheprovider` 时于 `pytest_sessionstart` 触发
  `AttributeError: module 'platform' has no attribute 'python_version'`
  INTERNALERROR。
- 处置：项目标准测试命令不带 `PYTHONPATH=src`（conftest.py 已把 repo
  root 加入 sys.path，`import src.platform...` 可正常解析，stdlib
  `platform` 不被遮蔽）。Round 2 各 Task 的 pytest 命令一律不加
  `PYTHONPATH=src`。此为环境陷阱而非本次实现缺陷，长期可考虑改名
  `src/platform` 或改用 src-layout 包名，属后续重构范围。

## Round 2 fresh 审计阻断项（2026-08-21）

### ISS-021（P0）迁移 backup guard 晚于自动 schema migration — CLOSED_WITH_EVIDENCE

- 证据：CLI `--apply` 先构造 `PlatformStore`；其初始化立即调用
  `apply_migrations()`，随后 `run_migration()` 才校验备份。
- 复现：061 副本在不存在备份目录时先从 61 升到 68，然后才抛
  `MigrationNotAuthorized`。
- 要求：readonly preflight 必须发生在任何可写连接/WAL/schema migration 之前；
  失败时 DB bytes/hash/size/migration count 不变。
- 关闭证据（R2-02）：`scripts/cognition_migrate_legacy.py` 的
  `preflight_migration()` 只读预检在任何可写 Store 之前执行；
  `tests/cognition/test_migration_preflight_cli.py` 覆盖无效备份 exit 2
  且 DB 零字节变化、dry-run 零 WAL/SHM、有效备份 apply 幂等。2026-08-21
  追加修复：陈旧断言“apply 到 068”改为动态读取 `MIGRATIONS` 声明的
  最新迁移（069 CAS 迁移加入后不再硬编码）。（原与 ISS-014 重号，现改
  编号 ISS-021。）

### ISS-022（P0）Research run API 缺少持久化 scope 授权 — CLOSED_WITH_EVIDENCE

- 证据：status/resume/cancel/decide/claims 只检查 session；service `get_run()`
  仅按 run ID 查询。citations/synthesize 接受调用者提供 scope，未与 run 对账。
- 影响：多主体/客户/项目环境可能跨 scope 读取或改变 run。
- 要求：session→IAM action→ScopeResolver→CognitiveContext→run scope comparison；
  全端点跨 principal/customer/project/test scope 负例零泄漏。
- 关闭证据（R2-03）：`src/platform/api/cognition_auth.py`
  `build_context`/`ResearchRunAccessPolicy`/`context_from_run`；全部 Research
  端点接入 IAM action permission + run 持久化 scope 对账；
  `tests/research/test_research_scope_authorization.py`（跨主体/客户/项目
  零泄漏、start scope 校验、citations/synthesize scope 固化）与
  `tests/research/test_research_concurrency.py`（resume/cancel/decide CAS
  单赢家）fresh 绿。（原 ISS-015，编号顺延为 ISS-022。）

### ISS-016（P1）Research Graph 不具备完整 plan/gap/counterevidence — CLOSED_WITH_EVIDENCE

- 证据：Planner 固定单问题；gap 仅追加“补充 证据”；无独立 counterevidence；
  两来源即判冲突。
- 要求：显式 typed nodes、真实 contradiction 条件、novelty/停止条件和每节点恢复测试。
- 关闭证据（R2-06）：planner/critic/reader 模块落地；deep_research typed plan +
  degraded/abstain；gap/counterevidence 为独立 typed 检索动作；冲突仅在互斥规范化
  数值/命题矛盾时成立（等值多来源=diversity）；novelty 连续两轮无新 span 停止；
  `tests/research/test_research_planner_counterevidence.py` 7 项 + 回归 269 项 fresh 绿。

### ISS-017（P1）Citation Verifier 未验证 Claim-support 语义 — CLOSED_WITH_EVIDENCE

- 证据：有 span 即写 `supports` 与 `verifier_score=1.0`；Verifier 只检查
  locator/source/scope/time，citation precision fresh 为 unmeasured。
- 要求：deterministic validity + support semantics 两层验证；评测使用人工 gold relation。
- 关闭证据（R2-07）：`research/claims.py` DeterministicClaimSupportVerifier
  （数值/单位/命题键/否定/主题重叠 → supports/contradicts/context/insufficient）；
  ClaimBuilder 初始 unverified；验证结果持久化回 claim_evidence（含 verifier
  id/version/input_hash/score/reason）；高重要性仅背景/不足 → gate 阻断；
  迁移 070 扩展 relation CHECK。`tests/research/test_claim_support_semantics.py`
  6 项 + research 72 项 fresh 绿。gold relation 评测口径在 R2-08 落地。

### ISS-018（P1）Research finalize 可产生假成功 — CLOSED_WITH_EVIDENCE

- 证据：Evidence bundle 和 Business Run 同步异常被宽泛捕获后忽略，Research
  Run 仍可写 succeeded。
- 要求：统一 UoW，故障注入覆盖 evidence/business/work/event；失败不得成功。
- 关闭证据（R2-04）：`_node_finalize` 引证门 + `_finalize_uow` 同一显式
  事务收敛 report/evidence/research/business/work/event+outbox，任一失败
  整体回滚且抛分类错误；`tests/research/test_research_terminal_integrity.py`
  8 项故障注入 fresh 绿；`reconcile_cognition.py` 终态对账 gate。

### ISS-019（P1）真实 dense provider 与 index identity — 部分关闭（identity/mismatch/配置 CLOSED；真实 provider BLOCKED_BY_EMBEDDING_PROVIDER）

- 证据：索引 ID 不含 provider/model/dimension/parameters；build API 不传 provider；
  当前环境没有本地 embedding 包，语义 recall=0。
- 要求：真实可配置 provider、build/query identity 校验和真实 release eval；
  provider 缺失时 `BLOCKED_BY_EMBEDDING_PROVIDER`。
- R2-05 已关闭部分：index identity 覆盖 provider/model/revision/dimension/
  normalization/params；build/query identity mismatch fail-closed；OpenAI-compatible
  adapter + provider_from_env（key 不落日志/artifact）。
  `tests/cognition/test_vector_provider_integration.py` 12 项 fresh 绿。
- 仍 BLOCKED：本机无可用真实 provider（无 sentence-transformers/fastembed/mlx，
  无 TAAS_EMBEDDING_* 凭据），语义 recall release eval 待授权后复跑（DEC-114：
  不得用 fake 向量放行）。

### ISS-020（P2）实施状态账本曾与现场事实冲突 — MITIGATED

- 证据：STATUS 曾写 live migration=61、tracked=0、Task 1–13 DONE；现场为
  migration=68、8 个 tracked 修改，且 G6–G9 有失败。DECISIONS 曾重复 DEC-107。
- 处置：Round 2 文档和 STATUS 已纠正；执行 Agent仍需修复重复 ID并把旧 READY
  记录标为被后续证据推翻。

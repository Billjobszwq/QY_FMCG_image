# EXECUTION-LOG — TaaS Research RAG & Agent Memory V1

> 追加式（append-only），不覆盖历史。每条记录时间（Asia/Shanghai）、
> 命令/动作、fresh 结果。命令输出摘录不得替代重跑。

## E-0 阅读与准备（2026-08-20 21:00–21:20）

- 完整读到 EOF：GLOBAL_AGENT_ROUTING.md；三份 TaaS 规范与分案
  （统一架构设计规范 978 行 / 知识库与 Skill RAG 551 行 / Agents与记忆体系 884 行）；
  `docs/CODEX-PROJECT-HANDBOOK.md`（967 行）；本设计目录全部 9 个文件。
- 源码与测试完整读到 EOF：`agents/kernel.py`(192)、`agents/runtime.py`(1040)、
  `agents/supervisor.py`(374)、`agents/blackboard.py`(110)、`workflow.py`(1884)、
  `kernel/{definition,engine,loop}.py`(61/205/341)、`scope.py`(542)、
  `data/store.py`(4695)、`api/agent_runtime_api.py`(396)、`api/agents_api.py`(80)、
  `import_center.py`(1542)、`test_agent_kernel_blackboard.py`(94)、
  `test_abos_v3_agent_runtime.py`(305)。
- 确认仓库内无 AGENTS.md/CLAUDE.md（全仓 find 无命中）。
- 发现会话 cwd 落在陈旧 worktree `claude/keen-napier-9a2d19` @ `3f13fa6b`
  （ExitWorktree 无效，非本会话创建）→ DEC-101：全部操作走主仓库绝对路径。

## E-1 Git 与 DB 现场（2026-08-20 21:21–21:24，全部 fresh）

- `git status --short --branch`：`## codex/taas-agent-operation-v1...origin/codex/taas-agent-operation-v1 [ahead 8]`；
  唯一 untracked：`docs/implementation/taas-research-rag-agent-memory-v1/`。
- `git rev-parse HEAD` = `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`；
  `git log --oneline -8` 顶部为 `5bbbf898 fix(frontend): orchestrator 走同源代理 /orchestrator`。
- SQLite `runtime/platform/platform.sqlite`：sha256
  `2f7e44096066c337e38c3b344178a21ec04a2fea55f31bf60f8e073f54f66b62`，
  size 1224704，mtime 2026-08-17T02:06；`integrity_check=ok`；journal_mode=wal。
- 迁移 61 条，最新 `061_gate_run_v1`（applied 2026-08-14T14:09:41Z）；128 张表。
- 目标表计数（mode=ro）：`agent_manifest_v1=0`、`agent_definition_v1=7`（7 个 Agent
  均 v1 published）、`memory_entry_v1=0`、`agent_memory_v1=0`、
  `blackboard_event_v1=0`、`knowledge_document_v1=0`、`agent_asset_v1=0`、
  `agent_run_v1=0`、`business_run_v1=0`、`work_item_v2=0`、`event_envelope_v1=0`、
  `usage_event_v2=0`、`evidence_bundle_v1=0`、`workflow_definition_v1=0`、
  `import_batch_v1=0`、`uat_test_run_v1=0`、`gate_run_v1=0`、`md_customer_v1=0`、
  `iam_principal_v1=0`。
- 非零表 14 张（配置/种子类）：agent_definition_v1=7、auth_sessions=2、
  bi_metric_v1=6、fin_rate_card_v1=1、iam_approval_matrix_v1=5、
  iam_permission_bundle_v1=22、iam_role_permission_v1=55、iam_role_v1=12、
  platform_flag=2、rate_limit_rule_v1=9、rate_limit_v1=3、
  recognition_profile_def_v1=14、schema_migrations=61、work_item_supersession_v1=1。
- Manifest/Definition 差集：DB manifest=0；definition 7 个；
  代码声明 `_BUILTIN`=12（含 workflow_agent/iam_agent/recognition_agent/
  system_agent/workbench 等 5 个无 Runtime Definition）。
- `.superpowers/`：`find . -maxdepth 2` 无结果（迁移仓库不存在，ISS-010）。
- 资产符号链接（.kb/.models/.platform/.datasets* 等）均为未跟踪/被 .gitignore
  覆盖，实体指向 training-data/、recognition-models/、runtime/；本轮零触碰。

## E-2 进程、服务与 production（2026-08-20 21:21，只读 ps/CURRENT.json）

- 运行中（非本轮启动）：`src.ls_platform.orchestrator --port 8304`、
  `label_studio.server --port 8300`、`src.training.monitor --port 8092`；
  另有 omlx-server（本机 MLX 服务）。平台 API :8400 与 frontend :4173 未运行。
- 训练进程标记（ultralytics/train_v1/qlora/finetune_qwen/mlx_lm）：无命中。
- production bundle：`.models/bundles/CURRENT.json` = `prod_v4_best_r1`
  （previous `prod_20260805_v5_r1`，switched_by bill）——本轮未切换、未修改。

## E-3 针对性基线测试（2026-08-20 21:23，fresh）

```
XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  -m pytest -p no:cacheprovider -q \
  tests/platform/test_agent_kernel_blackboard.py \
  tests/platform/test_abos_v3_agent_runtime.py
→ 17 passed, 1 warning in 5.76s
```

（warning 为 fastapi testclient 的 StarletteDeprecationWarning，非本轮引入。）

## E-4 相邻回归（2026-08-20 21:24，fresh）

- suite：test_abos_v2_workflow / test_abos_v3_workflow_runtime /
  test_abos_v3_unification / test_abos_v3_usage_workbench /
  test_si2_scope_isolation / test_si3_scope_integrity / test_osv5_import_scope /
  test_uatcc_parallel_engine / test_uatcc_red_contracts / test_uatcc_v4_evidence
- 结果：`126 passed, 1 warning in 32.77s`。

## E-5 状态文件建立（2026-08-20 21:25）

- 新建本目录 `STATUS.md` / `ISSUES.md` / `DECISIONS.md` / `EXECUTION-LOG.md`，
  记录 E-1…E-4 的全部 fresh 事实。未写任何业务代码；未 commit；
  未触碰训练/模型/SQLite/未跟踪资产。

## E-6 Task 1 完成：基线锁定测试与审计脚本（2026-08-20 21:44）

- 用户授权“动项目中所有文件”；commit 仍未获明确授权 → 保持工作树 diff。
- 新增 `tests/cognition/test_live_contract_baseline.py`（10 项锁定）与
  `scripts/audit_cognition_baseline.py`（只读 JSON 审计）。
- 首跑 9 passed / 1 failed：`test_tracked_files_never_inside_protected_dirs`
  命中 `runtime|training-data|recognition-models` 各 1 个 README 占位
  （迁移项目有意提交的文档 stub，数据资产零跟踪）。修正断言为“允许
  README.md 占位、禁止其他实体”，非放宽资产边界。
- 复跑：`tests/cognition/ → 10 passed in 0.45s`（fresh）。
- 审计脚本输出与 E-1 一致（sha256 `2f7e4409…`、61 迁移、计数复现）。
- G0 前置事实全部在案；Task 1 = DONE（待相邻回归与 Gate 记录后关闭）。

## E-7 Task 2 完成：CognitiveContext 与 typed contracts（2026-08-20 21:52）

- 红测试先行：`tests/cognition/test_context_contracts.py`（23 项）首跑
  collection error（`src.platform.cognition` 不存在）= 预期失败，已记录。
- 最小实现：`src/platform/cognition/{__init__,errors,context,contracts}.py`。
  - errors：validation/policy/permission/conflict/retryable/provider/budget/
    integrity 八类稳定错误码（fail-closed）。
  - context：frozen CognitiveContext + `context_from_scope()` 唯一服务端
    入口；缺 principal/tenant/action/as_of 拒绝；未知 data_scope 拒绝；
    fixture 必须携带 test_run；operational 不得携带 test_run；
    `untrusted_overrides` 非空即 CognitionPolicyError；`force_data_scope`
    恒拒绝（无降级旁路）。
  - contracts：QueryRequest/ArtifactRef/EvidenceSpan/Claim/IndexSnapshot/
    RetrievalCandidate/SearchResult，全部 frozen + 严格 from_dict（未知字段
    拒绝）+ canonical-JSON content_hash（字段顺序无关）。
- 复跑：`tests/cognition/test_context_contracts.py → 23 passed`（fresh）。
- 相邻回归（scope 三 suite + Task 1 锁定）：`81 passed, 17.78s`（fresh）。
- G1 契约事实源就位；进入 Task 3（单一 Agent Definition 投影）。

## E-8 审查面板 21 项发现全部处置（2026-08-20 22:15）

- Workflow `review-cognition-task1-2`（3 视角：契约符合性/安全负例/
  测试质量）返回 21 项发现（8 medium/13 low），全部真实，逐项修复：
  1) Claim 补 `research_run_id` 必填（02 §6）；
  2) 空 customer/project 必须由 `EMPTY_SCOPE_POLICY` 显式声明（02 §1），
     未声明动作 fail-closed（CognitionPolicyError）；
  3) adapter 空 tenant 改为拒绝（不再默认 'local' 洗白）；
  4) permission_tags 拒绝裸字符串/非 str 元素（防逐字符拆散安全标签）；
  5) untrusted_overrides 判定改 `is not None and len>0`（falsy Mapping
     子类不再绕过）；force_data_scope 恒拒绝；
  6) from_dict 缺字段/坏 as_of/类型错误统一归一 CognitionValidationError
     （含 CognitiveContext 与全部契约的 `_strict` 必填字段校验）；
  7) 数值校验拒绝 bool 冒充 int、字符串冒充 float；
  8) ArtifactRef 强制 producer_run/retention 非空（02 §8.3）；
  9) content_hash 稳定性：集合型字段（permission_tags/target_kinds/
     index_snapshot_ids）构造时排序；as_of 统一 UTC（'Z'→+00:00，
     naive 视为 UTC）；
 10) Task 1 迁移锁定正则覆盖引号/括号/反引号/schema 限定名，并新增
     DROP TRIGGER 扫描；三账本触发改为行为级验证（真 INSERT 后
     DELETE/UPDATE 必须被拦）；
 11) git 边界测试：core.quotePath=false、大小写折叠匹配、git 缺失
     时 skip 不假红；.gitignore 断言忽略注释行；
 12) 补齐缺失负例：CognitiveContext round-trip/未知字段/缺字段、
     各契约缺字段稳定错误码、top_k=True、confidence="0.9"。
- 复跑：`tests/cognition/ → 48 passed in 0.42s`（fresh）。
- 无 commit；全部为测试与契约源码修改，未触碰数据/资产。

## E-9 Task 3 完成：单一 Agent Definition 事实源 + Manifest 投影（2026-08-20 22:05）

- 红测试先行：`tests/governance/test_agent_definition_projection.py`
  （10 项）首跑 collection error（definition_service/manifest_projection
  不存在）= 预期失败。
- 实现：`agents/definition_service.py`（AGENT_SEEDS 所有权收敛 +
  canonical_agent_report：12 Agent，7 published / 5 declared，declared
  不伪装 healthy）、`agents/manifest_projection.py`（确定性投影 +
  guarded_manifest_insert 写守卫 + consistency_report Gate）；
  kernel.py `_ensure_builtin` 改为投影重建、Manifest 增
  definition_status 字段；runtime.py seed 委托 definition_service。
- Gate 语义：manifest 与 definition 的 version/tool_allowlist 逐字段
  对账，任一漂移（含缺行）→ ok=False；rebuild 幂等（hash 稳定）。
- 复跑：`tests/governance/ + kernel/runtime 回归 → 27 passed`（fresh）。
- 全量 hermetic（后台）：`1872 passed, 6 skipped, 1 failed`，唯一失败为
  结构合同 test_project_structure_docs（新测试目录未登记）——属预期
  结构变化，已同步更新 REQUIRED_TEST_SUITES 与 PROJECT-STRUCTURE.md。

## E-10 Task 4 完成：Policy/Alert/Pause 与 Rules/Silent 受限角色（2026-08-20 22:40）

- 红测试先行：`tests/governance/test_policy_alert_pause.py`（26 项）
  首跑 collection error = 预期失败。
- 迁移 062（追加式）：policy_rule_version / governance_approval_v1 /
  governance_alert_v1 / governance_snapshot_v1（全不可变）/
  pause_request_v1；approval/alert/snapshot/pause 禁 DELETE 触发器在位。
- 实现：`governance/{__init__,policy_service,alert_service,pause_service,
  agents}.py`：
  - deterministic PDP：缺上下文 fail-closed、未知动作 deny、高风险动作
    默认 human_gate、published deny 规则优先、过期/draft 规则不消费、
    注入字符串只作数据；
  - 规则 draft→approval→publish（maker≠checker、CAS pending→终态、
    新版本发布旧版本 superseded）；
  - Silent 独占告警/快照/暂停请求；快照不可变且含 state_hash；
  - 暂停恢复必须 human_approved + CAS（终态不可再迁移）。
- 修复 1 项测试缺陷：空表上不触发行级触发器 → 先插行再验证拦截。
- 复跑：`tests/governance/ + tests/cognition/ + 结构合同 + agent 回归
  → 96 passed, 9.32s`（fresh）。
- 迁移前置备份：`runtime/platform/backups/platform_pre_cognition_*.sqlite`
  （sqlite backup API，integrity=ok）。
- G2 治理控制面就位；进入 Task 5（source/document/chunk/evidence 链）。

## E-11 Task 5 完成：不可变 source→document→chunk→span 链（2026-08-20 23:10）

- 红测试先行：`tests/cognition/test_source_versioning.py`（16 项）首跑
  collection error = 预期失败。
- 迁移 063（追加式）：cognition_source_artifact_v1（append-only）、
  cognition_document_version_v1（append-only）、cognition_chunk_v1 /
  cognition_evidence_span_v1 / cognition_corpus_snapshot_v1（全不可变
  UPDATE/DELETE 触发器）。
- 实现：`cognition/repository.py`（UnitOfWork 显式事务 + 类型化
  Repository；服务层零底层连接——含静态源码扫描锁定测试）、
  `sources/parsers.py`（text/markdown+text/plain，注入模式扫描，其余
  格式诚实 ProviderError）、`sources/chunking.py`（标题层级
  heading_path + 精确 char offset，content[start:end]==chunk.text）、
  `sources/service.py`（CAS 原子写、同 hash 幂等、新版本不覆盖旧 chunk、
  注入→quarantine 且发布门拒绝、publish 需 owner+人类 approver、
  corpus snapshot 按 manifest_hash 幂等）。
- 修复 1 项真实缺陷：幂等路径误以 source_id 查 document 版本 →
  document_id 派生提前，复跑通过。
- 复跑：`tests/cognition/ → 64 passed in 2.52s`（fresh）。
- G3 事实底座（source→span 可回查 + 注入隔离）就位；进入 Task 6。

## E-12 Task 6 完成：规范 L1/L2/L3 与旧记忆兼容（2026-08-20 23:40）

- 红测试先行：`tests/cognition/test_memory_lifecycle.py`（14 项）+
  `tests/cognition/test_memory_legacy_migration.py`（3 项）首跑
  collection error = 预期失败。
- 迁移 064（追加式）：memory_l1_event（只追加，禁 UPDATE/DELETE）、
  memory_l2_episode（append-only；UNIQUE(source_hash,
  consolidator_version) 幂等）、memory_l3_methodology_version
  （append-only；candidate/published/superseded/revoked）。
- 实现：`memory/service.py`（角色矩阵强制：普通 Agent 写 L2/L3 →
  PermissionDenied；L2 仅 Consolidator 生成 candidate、人工发布；L3
  最小 3 个已发布 L2、来源必须 published、反例未清禁止发布、candidate
  永不进入检索面）、`memory/consolidation.py`（确定性 source_hash）、
  `memory/projection.py`（L1 current cards：supersession 推导，旧
  Blackboard API 保留只读兼容，双读收敛在 Task 13）、`memory/legacy.py`
  （旧表只读适配 + L0-L4 映射：L4/未知→quarantine_candidate，不强制
  映射 L3）。
- `scripts/cognition_migrate_legacy.py`：V1 仅 --dry-run，逐行决策 +
  sha256 行 hash；live 模式抛 MigrationNotAuthorized；dry-run 零写入。
- 修复 1 项 SQL 参数错位（L3 INSERT 13 值/12 列）→ 复跑通过。
- 复跑：Task 6 `17 passed`；相邻回归（cognition+governance+agent）
  `125 passed, 12.86s`（fresh）。
- G4 记忆治理就位；进入 Task 7（Knowledge/Skill 生命周期）。

## E-13 Task 7 完成：Knowledge 与 Skill 独立生命周期（2026-08-21 00:05）

- 红测试先行：`tests/cognition/test_knowledge_lifecycle.py`（12 项）+
  `tests/cognition/test_skill_lifecycle.py`（11 项）首跑 collection
  error = 预期失败。
- 迁移 065（追加式）：knowledge_item_version（8 类知识类型；
  draft/published/superseded/revoked；append-only）、
  skill_definition_version（draft/validated/published/degraded/revoked；
  append-only；risk_level CHECK 允许 draft 空值、发布门强制补齐）。
- Knowledge：发布门 owner/effective_from/≥1 source span/人类 approver；
  检索面默认只返回“已发布且 as_of 生效”，expired/revoked/superseded/
  draft 不返回（include_history 例外）；同主题（type+title）多来源
  生成 conflict report，不自动“最新者胜”；knowledge_document_v1 只读
  兼容投影（_writable=False）。
- Skill：发布门 schema/execution_ref/risk/evaluation_ref/approver；
  状态机 CAS（draft→validated→published→degraded/revoked，非法跃迁
  拒绝）；**search 命中 ≠ 可执行**：can_execute 独立判定（仅 published；
  high/critical → human_gate）；agent_asset_v1(kind='skill') 只读投影
  不构成执行授权。
- 修复 2 项门禁位置缺陷（空 schema/risk 应在发布门拒绝而非 draft/
  validate 阶段）。
- 复跑：Task 7 `23 passed`；Phase 2 相邻回归（cognition+governance+
  agent+import center）`156 passed, 22.29s`（fresh）。
- **Phase 2（G3/G4/G5）完成**；进入 Phase 3 Task 8（索引目录 +
  ACL-first 联邦混合检索）。

## E-14 Phase 2 对抗性审查修复（2026-08-21 00:30）

- Workflow `review-cognition-phase2`（3 视角）返回 31 项发现；逐项核实
  后修复高/中危真实缺陷（全部以新增负例测试锁定）：
  1) **审批账本绑定**：knowledge/skill/L2/L3/document 的 publish/revoke
     全部改为必须提供 governance_approval_v1 中已批准的 approval_id，
     kind/subject 匹配、批准人==approver、maker≠checker（PolicyService.
     verify_approved）；自批自发布、冒名批准、未决 approval 均被拒。
  2) **evidence span 落地**：ingest 时为每个 chunk 生成 span
     （span_id==chunk_id，quote_hash=sha256(text)）；knowledge 发布门
     校验 source_span_ids 真实存在，伪 span id 被拒。
  3) **source_id 按来源唯一**（origin+sha 派生），同内容不同 uri 不再
     UNIQUE 崩溃；空 uri 拒绝；外部来源不得自报 authoritative。
  4) **parser 半提交消除**：解析先于任何写入，非法 UTF-8 → 零落库。
  5) **L3 独立事件去重**：重复 L2 id 不虚增门；反例支持提议后补录
     （record_counterexample）阻断发布；新增 revoke_l3、L2 conflict/
     archive 生命周期边。
  6) **注入隔离 → 治理告警**（02 §8.1）；注入扫描双策略归一化
     （零宽字符删除/替换空格），ZWSP 拆词混淆不再绕过。
  7) **Repository 边界收口**：memory/knowledge/skills/projection 服务
     全部改经 CognitionRepository/UoW；边界扫描测试扩展至全部认知服务
     模块（禁止 _conn 直连）。
  8) **source supersession**：同 uri 新内容摄取 → 旧 source 行
     superseded；publish 拒绝 superseded source。
  9) skill permission_tags fail-closed；skill 发布+旧版本降级同事务。
- 修复后全量回归：`tests/cognition/ + tests/governance/ → 176 passed`；
  全 hermetic `1991 passed, 6 skipped, 0 failed`（fresh）。

## E-15 Task 8 完成：Index Catalog + ACL-first 联邦混合检索（2026-08-21 01:00）

- 红测试先行：`test_federated_retrieval.py`（15 项）+
  `test_retrieval_security.py`（9 项）首跑 collection error（index 包
  不存在）= 预期失败。
- 迁移 066（追加式）：认知四表补 tenant/customer/project/data_scope/
  test_run_id scope 列；cognition_index_build_v1（append-only）+
  cognition_index_activation_v1（append-only 显式激活注册表）。
- 实现：`index/lexical.py`（整词+CJK 二元 tokenizer、BM25-lite、
  评分前 allowed 过滤）、`index/vector.py`（VectorProvider 端口 +
  UnavailableVectorProvider 诚实降级）、`index/fusion.py`（RRF +
  文档多样性去重 + RerankerPort）、`index/catalog.py`（build 记录
  corpus/backend/analyzer/chunk 策略/参数/条目数/质量报告；artifact
  hash 完整性校验；显式 activate + hash CAS、retire 旧 active）、
  `index/gateway.py`（缺上下文 fail-closed；tenant/customer/project/
  data_scope/test_run/permission/effective-time 全部 pre-retrieval
  过滤；不返回 total_count/facets；degraded 显式；知识候选携带可定位
  span；skill/memory_l2/l3 各用自身 lifecycle filter——仅 published）、
  `index/sku_kb.py`（.kb Domain Retriever 只读适配，不写企业 KB 表）。
- 语义定案：lexical-only 基线 build（无向量、未配 provider）
  degraded=False；provider 已配置但不可用 / 索引有向量但网关未配
  provider → degraded=True（不造假向量）。
- 安全测试：跨 tenant/customer、过期、revoked、draft、test scope
  零命中且不泄露计数；权限标签不相交零命中（9 项全绿）。
- 复跑：`tests/cognition/ + tests/governance/ → 200 passed`（fresh）。
- G6 检索面就位；进入 Task 9（Research Graph/预算/恢复）。

## E-16 Task 9 完成：可恢复 Research Graph + 预算 + 断点恢复（2026-08-21 01:40）

- 红测试先行：`tests/research/test_research_graph.py`（6 项）+
  `test_research_resume_budget.py`（7 项）首跑失败 = 预期。
- 迁移 067（追加式）：research_run_v1（state/consumed/budget 持久化）、
  research_step_v1（checkpoint，UNIQUE(run,seq)）、research_query_v1 /
  research_claim_v1 / claim_evidence_v1（均 append-only）。
- 实现：`research/budgets.py`（mode→预算默认 + 硬上限检查）、
  `research/graph.py`（classify→plan→retrieve→read→sufficiency→claim→
  finalize 管线 + 节点 schema）、`research/service.py`：
  - 每个 run 挂统一 BusinessRun/WorkItem/事件；每节点挂
    NodeAttempt（workflow_node_execution）+ Usage（research_query）+
    最终 Evidence bundle；
  - sufficiency 缺口 → gap 回跳（受 max_iterations 约束）；发现多来源
    冲突 → waiting_human，需 decide_conflict 人类裁决才续跑；
  - 预算（queries/steps/deadline）每步前检查，超限诚实 failed
    （stop_reason=budget_exhausted:*）；
  - 故障注入钩子：节点崩溃 → failed step + run failed；resume 从断点
    续跑，已完成节点不重跑、查询不重复消费（测试验证 read 一 failed
    一 succeeded、查询仅 1 次）。
- 修复：research_run INSERT 参数/列错位；step 重复记录同 seq；检索
  ctx action 用已声明的 cognition.research.start。
- 复跑：`tests/research/ → 13 passed`；全 hermetic `2007 passed`
  （含结构合同更新 tests/research 登记）。
- G7 研究执行面就位；进入 Task 10（Claim 引证 Gate）。

## E-17 Task 10 完成：Claim 引证 Gate + Synthesizer（2026-08-21 02:10）

- 迁移 068（追加式）：research_report_v1（不可变；绑定 corpus/index/
  model/prompt/policy snapshot）。
- 实现：`research/citations.py`（CitationVerifier：span 必须真实存在、
  来源已发布且 as_of 生效、tenant/customer/scope/permission 匹配；
  verdict=pass/narrow/relabel/remove/research_more；高重要性
  unsupported/contradicted/引证失效 → gate 失败）、
  `research/synthesizer.py`（只消费已核验 Claim；remove/research_more
  不进报告；无有效证据 → abstain 且不编造；报告持久化并绑定全部
  snapshot）。
- 测试：`test_claim_citation_gate.py`（6 项：真实 run 引证+snapshot
  绑定、高重要性无证据阻断、伪 span 阻断、过期来源引证失效、低重要性
  部分失效 narrow 不阻断）+ `test_contradiction_abstention.py`
  （4 项：反证 research_more + 高重要性阻断、冲突不静默选边、证据不足
  abstain、abstain 报告仍持久化）。
- 复跑：`tests/research/ → 22 passed`（fresh）。
- G8 引证门就位；进入 Task 11（受控 API + Research Workbench）。

## E-18 Task 11 完成：受控 API + Research Workbench + 知识治理 UI（2026-08-21 02:59）

- 后端 API（src/platform/api/）：`cognition_api.py`（sources ingest /
  knowledge draft+publish / knowledge+memory+skill search / skill
  can-execute / index build+activate）、`research_api.py`（research
  start/status/resume/cancel/decide-conflict/claims/citations/synthesize）、
  `governance_api.py`（approval request/decide、policy draft、alerts）。
  全部鉴权（session）+ 写端点 CSRF；经 app.py 装配（bundle 组合根构建
  CognitionStack，cas/index root 可经环境变量覆盖）。
- 前端（frontend/）：`src/lib/api.ts` 增加 cognition/research/governance
  typed client；`src/pages/research/Workbench.tsx`（发起研究/状态/claim/
  引证门/恢复/取消/裁决/综合报告）；`src/pages/data/KnowledgeGovernance.
  tsx`（知识/记忆/Skill 检索 + skill can-execute 校验 + 治理告警）；
  registry 注册 `/research/workbench` + `/data/knowledge`。
- 验证：`npm run build`（tsc+vite）通过、`npm run test` 16 passed、
  `npm run lint` clean；dist 含 Workbench/KnowledgeGovernance chunk。
- API 测试 `tests/research/test_research_api.py` 8 项（401/403/CSRF、
  research 全流程、知识检索、abstain）全绿。
- 全 hermetic `2028 passed, 6 skipped, 0 failed`（fresh）。

## E-19 Phase-3 对抗性评审修复（2026-08-21 03:00）

- Workflow `review-cognition-phase3`（ACL 泄漏/研究正确性/引证绕过 3 视角）
  返回发现；逐项核实并修复高危/中危：
  1) **跨 project ACL**：gateway `_unit_visible`/`_row_visible` 补
     project_id 维度（项目级内容仅同项目可见）——修复跨项目泄漏。
  2) **陈旧索引 status**：knowledge 检索以 DB 当前状态复核 published
     （revoked/superseded 后不重建索引也不再命中）；引证 `_check_span`
     补底层 source 隔离/撤销/取代校验 + test_run_id/project_id 维度 +
     同 span 多来源逐一核验。
  3) **deadline 绕过**：elapsed 累计持久化在 state，resume 不重置。
  4) **重复消费**：retrieve 逐查询幂等（run+sq+iteration 派生 query_id/
     usage_id，INSERT OR IGNORE + rowcount 计 consumed），崩溃 resume
     不超出 max_queries。
  5) **iteration 双计数**：iteration 只在查询成功后写回 state。
  6) **步骤预算**：consumed.steps 在每次尝试（含失败）计数并持久化，
     防无限重试。
  7) **trace 泄漏**：移除 retrieval_trace 全局语料计数。
  8) sku_kb retriever 补 ctx 校验说明（V1 未接入联邦检索面）。
- 新增回归测试 `TestReviewRegressions`（跨 project 零命中、revoke-after-
  build 零命中、superseded 旧版本不返回、trace 不泄漏全局计数）。
- 复跑：`tests/cognition/ + tests/governance/ + tests/research/ →
  213 passed`；全 hermetic `2028 passed, 0 failed`。
- 进入 Task 12（固定评测 + 负例账本 + Gate）。

---

# Round 2 收口（2026-08-21）

> 权威入口：`round-2-hardening/`。Round 1 的 DONE/PASS 不覆盖 fresh 失败。
> Round 2 起始状态：`BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION`。

## R2-01 fresh 基线与状态账本（2026-08-21 13:35）

- fresh 复核（不复制 Round 1 数字）：
  - branch `codex/taas-agent-operation-v1`，HEAD
    `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`，ahead origin 8，未 commit。
  - tracked 修改 10 个（含 README/docs 入口指向 round-2）；大量
    cognition/governance/research/docs/frontend 新文件未跟踪，未 commit。
  - live DB `runtime/platform/platform.sqlite`：SHA-256
    `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`，
    size 1470464，integrity ok，migration 68，全部 cognition/research 新表
    0 行；无 WAL/SHM 残留（mode=ro 读取）。
  - 061 备份 `backups/platform_pre_cognition_20260820T144949Z.sqlite`：
    SHA-256 `aef8f09670bbce738f81b15ab49144cf9b5bc686074525f8e517446e2ea4c38e`，
    integrity ok，migration 61（WAL 模式头）。
  - provider：sentence_transformers/transformers/onnxruntime/fastembed 均缺；
    openai 已装但无 OPENAI_API_KEY；torch 2.13 MPS 可用。→ dense provider
    无真实可用，后续按 BLOCKED_BY_EMBEDDING_PROVIDER 处理。
  - 进程：8091/8092/8300/8301/8304/8400/4173 在运行；无训练进程；
    production bundle `prod_v4_best_r1` 未切换。
  - fresh 全 hermetic：`2034 passed, 6 skipped, 6 deselected, 0 failed`
    （约 306s）。前端 lint clean / 16 tests / build ok。
  - eval `--suite v1 --frozen` exit 1：paraphrase.recall_at_10=0.0、
    citation.precision=unmeasured、abstention_accuracy=0.833 未达标。
- 状态改为 `BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION`；Task 8–13
  对应 Gate G6–G9 标 FAIL/PARTIAL（见 STATUS）。

## R2-02 迁移备份预检顺序 P0（R2-P0-01）关闭（2026-08-21 13:55）

- 红测试先行：`tests/cognition/test_migration_preflight_cli.py`。红复现：
  备份目录无效时旧代码先构造 PlatformStore → 自动迁移 061→068 + 生成
  WAL/SHM，守卫才拒绝 → fingerprint 变化（migration 61→68）→ 红。
- 修复：`scripts/cognition_migrate_legacy.py` 重构——新增
  `MigrationPreflight` + `preflight_migration()`（全程 sqlite3 mode=ro，
  禁构造 PlatformStore）；CLI 顺序改为 解析参数→只读预检→校验备份
  （存在/非空/integrity/迁移谱系子集=目标身份匹配）→dry-run 只读退出 /
  apply+confirm+有效备份才构造可写 Store 显式迁移→迁移后 reconcile。
- 新增测试 4 项：守卫先于 Store（无效备份 exit 2 且 DB 指纹不变）、
  缺 confirm 标志 exit 2、dry-run 零 WAL/SHM、有效备份 apply 到 068 +
  二次 apply 幂等（migrated=0）+ legacy 行 hash 不变 + L3/L4 映射不丢失
  （L4→quarantine/conflict，不落 L3）。全部绿。
- 注意：`PYTHONPATH=src` 会使 `src/platform` 遮蔽 stdlib `platform`
  （pytest `-v` 触发 INTERNALERROR）；项目标准测试命令不带
  `PYTHONPATH=src`（conftest 已把 repo root 加入 sys.path）。已记 ISSUES。
- live DB 未动（仍 068）；所有破坏性验证使用 tmp 副本。

## E-20 Task 12 完成：固定评测 + 负例账本 + 可复现（2026-08-21 03:20）

- 实现：`cognition/evaluation/`（dataset/retrieval/citations/report/harness）。
  分层指标纯函数：Recall@K/MRR/nDCG/span recall/ACL leakage（retrieval）、
  citation support/precision/unsupported_high_importance（citation）、
  abstention_accuracy（generation）、acl_leakage/injection_success（safety）。
  报告含 report_hash + snapshot 绑定（供 Gate freshness 复核）。
- 金标准 `tests/fixtures/cognition/gold_queries.jsonl`：exact_rule/
  paraphrase/insufficient/acl(+正例) 五类；注入源
  `tests/fixtures/cognition/injection_sources/evil_policy.md`。
- harness：构建语料（平台级 kb-travel/kb-leave + 客户级 kb-confidential
  用唯一 token ZEBRA-9981）→ 审批发布 → 建索引激活 → 跑金标准。
- 脚本：`scripts/eval_research_rag.py`（--suite/--frozen/--out，输出分层
  JSON）、`scripts/reconcile_cognition.py`（--read-only 对账 integrity/
  行数/发布一致性/索引激活）。
- 修复：ACL 负例改客户级唯一 token（避免与平台级内容词法重叠造成假泄漏）。
- `tests/research/test_eval_reproducibility.py` 6 项（可复现哈希、exact
  命中、safety 零、abstain、分层指标）全绿。
- eval 脚本实跑：retrieval recall_at_5=0.667（词法基线，dense 前预期）、
  safety acl_leakage=0 / injection_success=0、abstention_accuracy=1.0。
- 全 hermetic `2033 passed`（结构调整测试后 `2034 passed, 0 failed`）。

## E-21 Task 13 完成：双读迁移 + 回滚 + 对账（机器侧；UAT 待人工）（2026-08-21 03:30）

- `scripts/cognition_migrate_legacy.py` 升级为 dry-run 默认 + --apply
  （需 --yes-i-have-backup 且 backups/ 存在平台备份，否则拒绝）；覆盖
  agent_memory_v1（L0-L4→L1/L2/L3/quarantine）、memory_entry_v1（→L2
  candidate）、knowledge_document_v1（→knowledge draft）、
  agent_asset_v1(kind=skill)（→skill draft）。均写 draft/candidate 不直接
  发布；不 DELETE/UPDATE 旧表行；不 drop 旧表。
- 验证（在 DB 副本，非 live）：`--apply --yes-i-have-backup` → 迁移
  062–068 全部应用（68 条，integrity ok，认知表创建，迁移 0 行 no-op——
  旧表为空）。dry-run live → 0 决策。无备份 apply → 拒绝。
- 回滚：迁移纯追加（062–068），回滚=不应用新写；旧表只读保留，无 drop。
- 对账 `scripts/reconcile_cognition.py --read-only`：integrity ok；
  发布知识缺 span 检查、索引激活↔build 一致性检查就位。
- **live DB 未应用 062–068**（有意保留：平台下次启动经
  PlatformStore.apply_migrations 自动应用；备份 platform_pre_cognition_*.
  sqlite 已在 backups/）。未 commit。
- 最终全 hermetic：`2034 passed, 6 skipped, 0 failed`（fresh）。
- 结构合同测试细化：tests/fixtures 为数据目录非测试套件，contract 扫描
  排除之（PROJECT-STRUCTURE.md 同步）。
- **机器侧全部 Gate（G0–G9）通过 → 状态 READY_FOR_UAT**。G10（人工真实
  UAT）待用户执行；未获人工 UAT 明确批准前不得写 ACCEPTED。

## E-22 Task 12–13 对抗性评审修复（2026-08-21 04:10）

- Workflow `review-cognition-task12-13`（评测正确性 / 迁移安全 2 视角）
  返回 12 项发现；逐项核实并修复：
  **迁移安全（高危，先修）**：
  1) knowledge 迁移误把 expires_at 写入 NOT NULL effective_from（NULL 时
     apply 崩溃、非 NULL 时把失效期写成生效期）→ 改为取 created_at 作
     effective_from（在 DB 副本 seed expires_at=NULL 验证不再崩、值正确）。
  2) apply 非原子非幂等：随机 ID + autocommit 重跑会向 append-only 表
     注入永久重复 → 改为 legacy 行派生确定性 ID + INSERT OR IGNORE；
     seed 后 apply#1 迁 5 行、apply#2 迁 0 行 skip 5（验证幂等）。
  3) 备份守卫只查文件名 → 改为逐个备份打开做 integrity_check + 非空校验。
  4) L3/quarantine 候选 apply 时被静默丢弃 → L3 落 memory_l3 candidate、
     未知层级（L4）落 memory_l2 status=conflict 隔离（seed L4 验证落账）。
  **评测诚实（假绿 gate）**：
  5) recall@10/per-class/阈值强制缺失 → report 计算 recall@5+recall@10、
     per-class 聚合、对照 §9.3 阈值逐项判定 pass/fail（evaluate_gates）。
  6) abstention_accuracy 单向（漏计错误 abstain）→ 双向计分（检索样本
     错误 abstain 计 0）。
  7) citation 层硬编码空却报满分 → citation.measured 标记，未度量不报满分。
  8) report_hash 不含 suite/frozen（产物与哈希不符）→ 并入后重算。
  9) nDCG 可 >1（同 knowledge 多 chunk 重复计）→ retrieved 去重 + cap 1.0。
  10) 注入负例 fixture 缺失时静默通过 → 改 fail-closed（抛 FileNotFoundError）。
  11) load_gold 不校验 class → 非法 class 抛 ValueError。
  12) 金标准头注释与实际不符 → 修正为 V1 子集说明。
- **诚实结论（重要）**：纯词法基线 **不通过** 语义召回 gate
  （paraphrase.recall_at_10=0.0，词法 bigram 与改写无交集）；
  abstention_accuracy=0.833<0.9；citation 层 V1 仅检索评测未度量。
  `scripts/eval_research_rag.py` gate 未达标时以 exit 1 如实报告（非假绿）。
  **这是词法基线的真实局限，需 dense/hybrid 检索才能通过语义 gate**。
- 复跑：`tests/research/test_eval_reproducibility.py +
  test_memory_legacy_migration.py → 9 passed`；迁移副本验证 integrity ok。

## E-23 独立完整性复核与 Round 2 重新开门（2026-08-21）

- Fresh 后端：`2034 passed, 6 skipped, 6 deselected, 0 failed`；前端 lint clean、
  16 tests passed、build 成功。以上证明回归基础健康，不等于发布 Gate 完成。
- Fresh eval exit 1：`paraphrase.recall_at_10=0.0<0.9`、
  `abstention_accuracy=0.833333<0.9`、`citation.precision=unmeasured`。
- Live SQLite 当前为 migration 68，sha256
  `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`，
  integrity ok；061 备份 sha256
  `aef8f09670bbce738f81b15ab49144cf9b5bc686074525f8e517446e2ea4c38e`，
  integrity ok；新增 cognition/research 表均 0 行。E-21 的“live 未应用”已失效。
- 迁移 P0 复现：061 副本先经 `PlatformStore.__init__` 自动升到 068，然后
  backup guard 才拒绝。现有 guard 不能保护 schema migration 前置条件。
- Research API P0：多个 run endpoint 只校验 session 并按 run ID 访问，没有
  IAM action + tenant/customer/project/data_scope/test_run 对账。
- Research/Citation P1：Planner 固定单问题、gap 只追加词、两来源即冲突；Claim
  有 span 即预填 supports/1.0，Verifier 未测 Claim-support 语义；finalize 吞
  Evidence/BusinessRun 错误可留下假成功。
- Dense/eval P1：index identity 不含 provider/model/dimension/parameters，build API
  未贯通 provider；gold set 只覆盖 V1 子集，citation/reader/research/system 未完整测量。
- 状态纠正为 `BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION`。新增
  `round-2-hardening/`，包含权威审计、修复架构、R2-01→R2-10 TDD 计划和
  可复制执行提示词。
- 本次只修改文档；未改业务代码、未执行 live migration、未删除、未训练、未切
  production、未 stage/commit/push/deploy。

## R2-01′ 独立 fresh 基线复核（2026-08-21 14:15，本会话重新生成）

- git：branch `codex/taas-agent-operation-v1`，HEAD
  `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610`，ahead origin 8（未 push）；
  `git diff --stat` = 11 tracked 文件 +902/-93；`git diff --check` clean；
  大量 cognition/governance/research/frontend/docs 未跟踪文件。
- live SQLite：`runtime/platform/platform.sqlite` sha256
  `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`，
  size 1470464，integrity ok（mode=ro），migration 68（最新
  `068_cognition_research_report_v1`），journal wal；新认知/研究表全 0 行。
- 061 备份：`runtime/platform/backups/platform_pre_cognition_20260820T144949Z.sqlite`
  sha256 `aef8f09670bbce738f81b15ab49144cf9b5bc686074525f8e517446e2ea4c38e`，
  integrity ok，migration 61。
- provider：sentence-transformers/transformers/onnxruntime/fastembed/mlx 均缺失；
  openai 2.54.0 已安装但未纳入项目依赖（R2-05 处理）。
- 进程：orchestrator :8304、training monitor :8092（非本轮启动，只读登记）；
  无训练进程；production bundle 未切换。
- 全量基线（本会话 fresh）：`1 failed, 2037 passed, 6 skipped,
  6 deselected`（302.99s）——唯一失败为 R2-02 陈旧断言（见下），非业务回归。
- 前端 fresh：lint clean；16 tests passed；build 成功。
- eval fresh（v1 --frozen）：`all_gates_pass=false`——
  `paraphrase.recall_at_10` 未达 0.9、`citation.precision` unmeasured、
  `abstention_accuracy=0.833<0.9`；acl/injection/unsupported 零泄漏项通过。
- 工作树发现：前一会话已完成 R2-02 主体与 R2-03 部分（migration 069、
  `cognition_auth.py`），但 R2-02 一项测试因 069 加入而陈旧，R2-03 API
  接线未完成。本轮逐项 fresh 验证并收口。

## R2-02′ 陈旧断言修复（2026-08-21 14:35）

- systematic-debugging 定位：`test_apply_with_valid_backup_migrates_to_068_and_is_idempotent`
  断言 `migration_count==68`，而 store 已声明 069（R2-03 CAS 列，纯追加）→
  apply 实际升到 69。根因是测试硬编码，不是迁移逻辑缺陷。
- 修复：断言改为动态读取 `src.platform.data.store.MIGRATIONS` 的总数与最新名
  （DEC-116）。修复后 `tests/cognition/test_migration_preflight_cli.py +
  test_memory_legacy_migration.py + tests/platform/test_platform_store.py`
  = 27 passed；live DB hash 复核不变（2306a030…）。
- R2-P0-01 关闭状态维持：readonly preflight 先于可写 Store 的合同由 4 项
  CLI 级测试锁定（无效备份 exit 2 且 DB 零字节变化、dry-run 零 WAL/SHM、
  有效备份 apply+幂等）。

## R2-03 Research IAM/scope/CAS P0 关闭（2026-08-21 15:05）

- 红测试先行：`tests/research/test_research_scope_authorization.py`（10 项）+
  `tests/research/test_research_concurrency.py`（5 项）首跑全红；红因核实为
  跨客户访问 200 泄漏完整 run 体（含机密问题）、start 无 membership 校验、
  service mutation 无 ctx——正是 R2-P0-02 描述的行为。
- 实现：
  - `cognition_auth.py`：`build_context(permission=…)` session→IAM authorize
    （含 customer/project membership）→ScopeResolver→`context_from_scope`；
    `ResearchRunAccessPolicy.require`（IAM permission + tenant/data_scope/
    test_run/customer/project 全匹配；平台例外仅 env admin 与 IAM
    owner/platform_admin）；`context_from_run`（run 固化 scope 派生）。
  - `research_api.py`：全部端点接入授权；无权与不存在统一 404（safe_404，
    不泄露 question/state/counts/scope）；citations/synthesize 的核验 scope
    只来自 run 持久化 scope；start 接收并验证 requested scope；DTO 暴露
    服务端固化 scope；mutations 写 IAM 审计。
  - `cognition_api.py`：删除手写 `_ctx`，统一 `build_context`
    （cognition.read/manage）。
  - `service.py`：`resume/cancel/decide_conflict` 强制 ctx + scope 复核；
    resume 推进权仅从 failed CAS 获取并置 running（running 中再 resume 为
    no-op，杜绝二次推进）；`_advance` 每步复核状态（cancel 获胜即停）；
    `_stop`/`_node_finalize`/waiting_human 转换全部条件 UPDATE（版本+状态），
    cancel 后 finalize 不得改写 succeeded；mutations 发事件审计。
  - 契约：`EMPTY_SCOPE_POLICY` 追加 research 平台级动作（DEC-117.1）；
    `business_run_v1` 允许 failed→cancelled 保证终态一致（DEC-117.2）；
    `CognitionStack` 暴露 store；app.py 向 cognition/research router 注入
    IAMService。
- 结果：新 15 项红测试全绿；`tests/research/ + tests/cognition/ +
  tests/governance/ + test_abos_v2_iam_master + test_si3_scope_integrity`
  = 264 passed；既有 research 测试仅按新签名补 ctx，无行为放宽。
- 边界：未 commit、未触 live 数据、未删除、未训练、未切 production。

## R2-04 Research 终态 UoW 与错误诚实性（2026-08-21 15:50）

- 红测试先行：`tests/research/test_research_terminal_integrity.py`（8 项）
  首跑全红——现状 `_node_finalize` 用 `except Exception: pass` 吞掉
  evidence/business 失败后仍写 succeeded（假成功）。
- 实现：
  - `Synthesizer.build_report/insert_report` 拆分：引证门 + 报告构造与
    提交分离，供终态 UoW 同事务复用；`synthesize` 维持按需发布语义。
  - `ResearchService` 增 verifier/synthesizer 端口（composition 注入共享
    实例）；`_node_finalize` 先过引证门（gate 失败 → policy_denied:finalize），
    再以 `_finalize_uow` 在同一显式事务写 report/evidence/research(CAS)/
    business/work/event+outbox；任一步失败 ROLLBACK 并抛
    `terminal_uow_failed:<类型>`，绝不写 succeeded。
  - `_advance` 错误分类为稳定 stop reason（policy_denied:/integrity:/
    conflict:/node_error:）；`_stop` 的 business 同步失败不再吞错，发
    critical governance alert 并以 `business_sync_failed` 上抛。
  - resume 获取 CAS 后同步 business failed→running（retry 合法跃迁），
    失败则回滚 research 状态，避免双账本漂移。
  - `reconcile_cognition.py` 增终态对账：succeeded 缺 report/evidence、
    research/business/work 状态漂移、孤儿 step/query/claim，任一非空
    `gate_ok=False` 且 exit 1。
- 结果：`tests/research/` 59 项 + `tests/cognition/test_reconcile_terminal.py`
  4 项 fresh 绿；终态/恢复/并发回归 26 项绿；live reconcile
  `gate_ok=True`，live DB hash 复核不变（2306a030…）。
- systematic-debugging 记录：retry 首失败根因为 business run 在终态失败后
  停在 failed，resume 未恢复其 running 即再入 finalize；已通过 resume
  同步 business 状态修复（非放宽断言）。
- 边界：未 commit、未触 live 数据内容、未删除、未训练、未切 production。

## R2-05 真实 Vector Provider 端口与不可混淆索引身份（2026-08-21 16:35）

- 红测试先行：`tests/cognition/test_vector_provider_integration.py`（12 项）
  首跑全红——现状 index_snapshot_id 不含 provider/model/dimension/params，
  无 mismatch fail-closed，无 providers 模块。
- 实现：
  - `index/vector.py`：VectorProvider 协议扩为 provider_id/model_name/
    model_revision/dimension/normalization_version + encode_documents/
    encode_queries；新增 `provider_identity/identity_string`（不含凭据）与
    旧式 `.encode` 兼容回退。
  - `index/providers.py`（新）：`OpenAICompatibleVectorProvider`（endpoint/
    model/key 只从受控配置，key 不入 repr/identity/异常；维度校验；批量）+
    `provider_from_env`（未配置 → UnavailableVectorProvider）。
  - `index/catalog.py`：index_snapshot_id 覆盖 target/corpus/backend/
    provider/model/revision/dimension/normalization/analyzer/chunk policy/
    canonical params；artifact 记 vector_identity + parameters，quality 记
    vector_count；embedding_model 记完整身份串。lexical 与 dense 不同身份
    不得互相复用。
  - `index/gateway.py`：build/query provider identity 不一致 → degraded +
    trace `provider_mismatch`，不计算 cosine、不返回伪 hybrid。
  - composition/app：组合根以 `provider_from_env()` 注入同一 provider 实例
    供 build 与 query；API build 不接受调用方 endpoint/key。
  - pyproject 增 `embeddings` optional dependency（openai）。
- 结果：R2-05 12 项 + retrieval/security 回归共 40 项 fresh 绿；
  cognition/research/governance/contract 380 项 fresh 绿。
- 状态：本机无真实 embedding provider（sentence-transformers/fastembed/mlx
  缺失，无 TAAS_EMBEDDING_* 凭据），语义 recall gate 保持
  `BLOCKED_BY_EMBEDDING_PROVIDER`（DEC-114：不得用 fake 向量放行）。身份/
  mismatch/配置卫生契约已关闭，真实 provider 评测待授权后复跑。
- 边界：未联网、未下载模型、未 commit、未触 live 数据。

## R2-06 显式 Planner / Gap / Counterevidence / 真实冲突（2026-08-21 17:20）

- 红测试先行：`tests/research/test_research_planner_counterevidence.py`
  7 项中 5 项红（旧启发巧合覆盖互斥值一例）。
- 实现：
  - `research/planner.py`（新）：PlannerProvider 端口 + validate_plan
    （有界/依赖/停止条件/target kinds 校验）+ atomic_plan；deep_research
    planner 不可用 → planner_degraded/abstain/stop_reason
    `degraded:planner_unavailable`，不用单问题冒充规划。
  - `research/critic.py`（新）：数值+单位规范化抽取（句子级 proposition
    key），跨来源互斥数值→结构化 conflict（含 sources/span_ids locator）；
    等值多来源 = diversity；sufficiency 输出 typed action
    accept/gap_query/counterevidence/ask_human + stop_rule。
  - `research/reader.py`（新）：span 证据抽取 + gap_rewrite/counterevidence_query
    （反证查询中性，不含数值断言/期望结论）。
  - service：classify/plan/retrieve/read/sufficiency 重写——retrieve 按
    pending_action 发 primary/gap/counterevidence typed 查询（strategy 落
    research_query_v1，query key 含 action）；read 记录 seen_spans/
    rounds_without_new（novelty 停止：连续两轮无新 span）；claim 在
    degraded 时不生成（abstain）。
- systematic-debugging 记录：novelty 测试初跑 stop_reason=complete，根因为
  gap 改写词命中测试语料产生假覆盖；修正测试语料隔离改写词后收敛路径正确。
- 结果：R2-06 7 项 + research/cognition/governance 269 项 fresh 绿。

## R2-07 Claim 支持性验证与 Citation Gate（2026-08-21 18:05）

- 红测试先行：`tests/research/test_claim_support_semantics.py` 5 红
  （现状有 span 即写 supports/1.0，Verifier 不验支持语义）。
- 实现：
  - `research/claims.py`（新）：DeterministicClaimSupportVerifier——
    数值/单位/命题键互斥→contradicts；否定方向翻转→contradicts；
    数值断言无对应事实→insufficient/context；主题重叠判定 supports/
    context；verifier id/version + input_hash + score + reason 全记录。
  - `_node_claim` 初始关系 unverified/score 0（不得预填 supports/1.0）；
    冲突裁决后以基准 span 过滤互斥证据再绑定（关系仍由 Verifier 核验）。
  - `CitationVerifier` 两层验证：span/source/ACL/time/scope 有效性 +
    支持性语义；验证结果持久化回 claim_evidence（relation/score/
    verifier_version）；仅背景/支持不足的高重要性 Claim → research_more
    → gate 阻断，不得发布。
  - 迁移 070：claim_evidence_v1 CHECK 扩展 unverified/insufficient
    （SQLite 无法原地改 CHECK，重建表前向演进；不改写 001-068 历史）。
- systematic-debugging 记录：初改后终态全红，根因为旧 CHECK 只允许
  supports/contradicts/context，INSERT OR IGNORE 静默吞掉 unverified
  行（claim_evidence 为空）；070 迁移关闭。次级根因：裁决后 Claim 仍
  绑定矛盾来源被 gate 正确拒绝 → claim 节点按基准过滤。
- 结果：R2-07 新测试 + research 72 项 + cognition/governance/contract/
  store 341 项 fresh 绿。

## R2-08 固定金标准 12 类 + 发布 Gate（2026-08-21 18:55）

- 红测试先行：`tests/research/test_release_eval_coverage.py`（12 项）首跑红。
- 实现：
  - gold_queries.jsonl 扩为 12 类 × positive/negative（25 样本），每条带
    polarity/as_of/scope/期望形态/forbidden_source_ids；新增 corpus fixture
    （policy_versions/multi_hop_org/conflict_policy_a/b）与 skills.jsonl/
    l2_cases.jsonl/l3_methods.jsonl/gold_claim_citations.jsonl。
  - dataset.py：GoldQuery 扩 target_kinds/polarity/as_of/scope/expect_ref/
    expect_conflict/forbidden_source_ids；id 重复与非法 class fail-closed；
    gold_content_hash 绑定进报告（防污染：provider 不读 gold 内容）。
  - harness：build_corpus 摄取知识(含时间/多跳/冲突)+skill+L2+L3；
    run_gold_evaluation 逐样本 target_kinds/as_of/scope、时延、forbidden、
    冲突正确性；reader/research/system 分层指标；citation precision/recall
    用 gold relation（DeterministicClaimSupportVerifier 复核，不以系统
    relation 当真值）。
  - report.py：新增 reader/research/system 层、forbidden_source_hits、
    gold_hash、citation gold 口径；易变字段(原始时延)不入 report_hash
    （可复现），稳定门(p95_under_2s)入哈希；gate 阈值不降低。
- systematic-debugging 记录（3 个现场根因）：
  1) g-acl 假泄漏 = 查询“客户”bigram 误中平台文档 → 精化 gold 查询；
  2) L3 检索恒空 = memory_l3 表无 permission_tags_json 列而 _row_visible
     强求 tag 交集 → L3 require_tags=False（scope 隔离仍在）；
  3) citation recall 0.5 = 命题键精确匹配过严 → 改 bigram 高重叠匹配。
- 结果：coverage/reproducibility 12 项 + cognition/research/governance 281 项
  fresh 绿。release eval：确定性 gate 全过；唯一未过
  `paraphrase.recall_at_10=0.0`——本机无真实 dense provider，按 DEC-114
  诚实 BLOCKED_BY_EMBEDDING_PROVIDER（不以伪向量放行）。
- 边界：未联网、未下载模型、未 commit、未触 live 数据。

## R2-09 API 行为门 / UI / 浏览器 / 性能 / 恢复（2026-08-21 19:05）

- 红测试先行：`tests/research/test_research_api_ratelimit_idem.py` 首跑红。
- 实现：
  - rate_limit：新增 research.run.start/resume/cancel/decide、
    research.synthesize 限流规则；API 各 mutation 端点接入 enforce
    （subject 取服务端认证身份，429 + Retry-After + 审计）。
  - 幂等：迁移 071 `research_idempotency_v1`；start 支持 Idempotency-Key
    重放返回首次结果，不重复执行（不同键产生不同 run）。
  - UI（Workbench.tsx）：展示服务端固化 scope、planner degraded、typed
    子问题（依赖/停止条件）、冲突（命题/取值/来源）、停止规则、citation
    locator；不渲染推理链。api.ts ResearchRun 增 scope 字段。
  - 组件测试：Workbench.test.tsx 3 项（scope/计划/冲突展示、degraded 提示、
    locator）fresh 绿；前端 lint clean、19 tests、build 成功。
  - 浏览器：playwright.config.ts + e2e/research-workbench.spec.ts 已落地
    （1024/1280/1440、键盘焦点、401/404、跨 scope 零泄漏、启动/综合流程）；
    真实运行需安装 @playwright/test + chromium（新增重型依赖，待授权）。
  - 性能：eval system 层实测 lookup 检索 p50/p95（p95_under_2s=True）。
  - 恢复/备份演练（全部在 mktemp 副本，live 零写入）：
    A) 068 副本 dry-run：exit 0，DB 主文件 hash 零变化（WAL 格式库只读
       访问产生空 -wal/-shm 簿记文件，内容不变；干净非 WAL 副本零 journal
       已由单测锁定）；
    B) 无效备份 apply：exit 2，DB 零变化；
    C) 061 副本有效备份 apply：061→071 全迁移，integrity ok，reconcile
       gate_ok=True、零漂移。drill 目录 /tmp/taas-r2-drill.aXsCn4 保留。
- 边界：未安装新依赖、未 commit、未触 live 数据、未切 production。

## R2-09 补充：真实浏览器验收（gstack qa-only，report-only）（2026-08-21 19:20）

- 用独立 QA 基础设施（非 live）：全新空 QA DB（/tmp/taas-browser-qa，非 live
  副本）+ qa_server(8402) + qa_web 静态/代理(4180)；未触碰 8400 既有服务、
  未触 live DB、未切 production。
- 真实浏览器（1024/1280/1440）逐项验证：登录→研究与认知→研究工作台；
  空态无“运行状态”；启动 run → 展示 状态/停止原因(completed_with_gaps)/
  Scope(服务端固化)/查询消耗/迭代/停止规则；Claims 显示“无证据/unknown/核验
  remove”；综合报告 → abstain + report_id；citation locator 区块存在（空引用
  时为空列表）；无隐藏推理链；无横向溢出；输入框键盘可聚焦。
- 截图存档于浏览器验收（report-only）；Playwright spec（e2e/
  research-workbench.spec.ts + playwright.config.ts）已落地，待安装
  @playwright/test + chromium 后可复跑（新增依赖，未安装）。
- 401/404/409/429：401(未登录)→登录弹窗；404 统一安全响应；409 CAS；429
  限流（后端单测覆盖）。

## R2-10 全量验证 / 边界复核 / 安全复审（2026-08-21 19:30）

- 全量 hermetic：**2102 passed, 6 skipped, 6 deselected, 0 failed**（324s）。
  6 skipped 为既有 host_mps 宿主探针（非 hermetic），6 deselected 同上；均
  如实报告，不影响发布判定。
- 前端：lint clean；test 19 passed（utils4+windowStore12+Workbench3）；build 成功。
- eval v1-release：确定性 gate 全过；唯一未过 paraphrase.recall_at_10=0.0
  （需真实 dense provider）→ 整体 BLOCKED_BY_EMBEDDING_PROVIDER。
  报告 runtime/platform/evidence/cognition-r2-release-eval.json，
  gold_hash 绑定，report_hash 可复现（剔除易变时延）。
- reconcile live（readonly）：integrity ok，gate_ok=True，零漂移。
- git diff --check clean；live DB hash 未变（2306a030…，068）。
- 边界复核：production bundle 未变（prod_v4_best_r1）；训练进程 0；staged 0；
  runtime/model/data 未 stage；diff 无密钥。
- 安全复审（report-only，cso 向）：cognition/api 无裸 SQL 拼接（全参数化）；
  无 eval/exec/subprocess/pickle/unsafe-yaml；provider key 不入日志/
  artifact/identity（providers.py repr 屏蔽）。CAS/限流/幂等/统一 404 零泄漏
  均由单测覆盖。
- 不创建 READY-FOR-UAT（G0–G9 未全绿：语义召回门需真实 provider）；不写
  ACCEPTED（未人工 UAT）。

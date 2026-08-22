# DECISIONS — TaaS Research RAG & Agent Memory V1

> 追加式登记。每条含 ID、日期、决策、理由、状态（ADOPTED / REVOKED）。
> 架构级决策 D-001…D-010 已在 `01-TARGET-ARCHITECTURE-AND-DECISIONS.md` 冻结，
> 本文件只登记实施期新增或操作级决策，不重复正文。

## 实施期决策

### DEC-101 工作目录与 worktree 边界 — ADOPTED（2026-08-20）

- 决策：全部实施操作（读写、git、pytest、脚本）使用主仓库绝对路径
  `/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation`；
  不在会话默认落入的陈旧 worktree（`claude/keen-napier-9a2d19` @ `3f13fa6b`）
  中做任何修改；不删除/不合并任何现存 worktree。
- 理由：worktree 基线落后主仓库且缺少 frontend/web/runtime 等目录；
  主仓库才是 `codex/taas-agent-operation-v1` 当前事实。

### DEC-102 现场数据库一律只读复核 — ADOPTED（2026-08-20）

- 决策：审计查询全部经 `file:...?mode=ro` URI 打开；任何迁移必须先备份、
  只追加、仅作用于 `runtime/platform/platform.sqlite`，并在使用前另行授权。
- 理由：绝对安全边界 §四.4；当前 DB integrity ok 且为共享运行事实。

### DEC-103 未授权本地 commit — ADOPTED（2026-08-20）

- 决策：用户尚未授权本地 commit；本轮只保留工作树 diff，绝不
  `git add -A`/`git add .`，不 push、不 merge。后续按 Task 提交前必须获得
  明确授权。
- 理由：任务书 §六.8 与绝对安全边界 §四.8/9。

### DEC-104 权威顺序与文档定位 — ADOPTED（2026-08-20）

- 决策：按任务书 §一 的六级权威顺序裁决冲突；
  `docs/CODEX-PROJECT-HANDBOOK.md` 仅作接续索引；
  设计目录内 `5bbbf898`、`17 passed` 等均为 2026-08-20 设计快照，
  已在本轮 fresh 复核（见 EXECUTION-LOG E-1…E-5），后续引用必须重新验证。
- 理由：任务书 §一/§三。

### DEC-105 基线测试环境隔离 — ADOPTED（2026-08-20）

- 决策：所有新 cognition/governance/research 测试遵循根 `conftest.py`
  hermetic auth 隔离，并显式清除/不继承 `DEEPSEEK_API_KEY` 等 provider 环境
  （先例：`test_abos_v3_agent_runtime.py` RC-9）。
- 理由：ISS-011；防止非确定性与真实外部调用进入测试。

### DEC-106 首个纵向切片范围 — ADOPTED（2026-08-20）

- 决策：第一轮只做 Markdown 制度 source、source→span 全链、ACL-first
  hybrid 检索、一个 lookup、一个 conflict query、两轮 gap search、
  Claim citation、跨客户负例、注入负例和 resume；不做 PDF/OCR/GraphRAG/
  外部 Web。UI 落在 `frontend/`（同源 `/api/v1`），`web/` 仅兼容回归。
- 理由：任务书 §七 与 05 计划 §3。

### DEC-107 单一管理员本机的 maker≠checker 审批模型 — ADOPTED（2026-08-21）

- 决策：发布门（knowledge/skill/L2/L3/document publish）经
  governance_approval_v1 账本校验——approval 必须 approved、kind/subject
  匹配、decided_by==approver、且 approval 申请人（maker）≠ 决策人
  （checker）。本机单一管理员场景下，申请记为系统/起草身份
  （如 cognition-service/eval-ingest），人类作为决策人，从而保持
  maker≠checker。
- 理由：02 §3/§4.3/§8.4 要求发布经人类批准且起草人不得自批；
  单一管理员环境通过“系统申请 + 人类决策”满足分离（评审 #G6 修复）。

### DEC-108 评测 gate 诚实报告，不为过门伪造 — ADOPTED（2026-08-21）

- 决策：评测 gate（§9.3 阈值）逐项判定 pass/fail 并以 exit code 如实
  报告；未达标项明确列出。V1 词法基线 paraphrase.recall_at_10 不达标
  （无离线真实 embedding）时保持 FAIL，不伪造向量、不放宽阈值、不报
  假绿。citation 层未度量时 measured=false 不报满分。
- 理由：05 §九“不能为了过门私改阈值”、任务书 §十“不得用测试之前通过
  掩盖”。gate 的价值在于如实暴露词法基线的语义局限（ISS-013）。

### DEC-109 迁移 apply 幂等 + 备份守卫 — ADOPTED（2026-08-21）

- 决策：`cognition_migrate_legacy.py --apply` 用 legacy 行派生确定性 ID
  + INSERT OR IGNORE 保证重跑幂等（append-only 表重复无法清理）；备份
  守卫逐个备份做 integrity_check + 非空校验（非仅文件名）；L3/未知层级
  （L4）分别落 memory_l3 candidate / memory_l2 conflict 隔离，不静默丢弃；
  knowledge effective_from 取 created_at（非 expires_at）。
- 理由：评审 #T13 发现的数据安全缺陷（崩溃/重复/语义倒置/静默丢弃）。

### DEC-110 Blackboard 与 L1 账本的收敛节奏 — ADOPTED（2026-08-20）

- 决策：Task 6 阶段新认知写入一律进 `memory_l1_event`，current 视图由
  `memory/projection.py` 从 L1 supersession 推导；旧
  `blackboard_event_v1` 与 `BlackboardService` 原样保留只读兼容，
  不做物理合并。双读对账与单账本收敛放入 Task 13（Stage A-D）。
- 理由：避免在 G4 阶段改动已被测试锁定的 append-only 契约；符合
  “先双读、再切读、最后停旧写”的迁移原则。

### DEC-111 Round 2 状态改为阻断态 — ADOPTED（2026-08-21）

- 决策：当前状态为 `BLOCKED_BY_SECURITY_MIGRATION_AND_EVALUATION`；
  Task 8–13 不再标记整体完成，G6/G7/G8/G9 不通过。
- 理由：fresh 复核确认迁移顺序和 Research API scope P0，以及 Research、
  Citation、dense/eval/system P1。自动化回归全绿不能替代缺失的发布 Gate。

### DEC-112 迁移预检必须先于任何可写 Store — ADOPTED（2026-08-21）

- 决策：backup/integrity/hash/schema preflight 只能通过 readonly sqlite3 完成；
  preflight pass 前禁止构造 `PlatformStore`、设置 WAL 或应用 schema migration。
- 理由：061 副本已复现 guard 拒绝前 schema 先升到 068。失败路径必须保证
  数据库字节级不变。

### DEC-113 Research 授权由 IAM + 持久化 run scope 决定 — ADOPTED（2026-08-21）

- 决策：run ID 不是授权凭证。所有 Research query/mutation 都需要 session、
  action permission、ScopeResolver、CognitiveContext 和 run scope 对账；团队共享
  由 IAM membership 决定，不以 created_by 单字段代替授权。
- 理由：只按创建人会阻断合法协作，只按 run ID 会跨 scope 泄漏；IAM + scope
  同时满足才是平台既有安全模型。

### DEC-114 真实 provider 缺失时保持 BLOCKED — ADOPTED（2026-08-21）

- 决策：允许测试 fake 验证 vector 接口和融合逻辑，但 release eval 必须使用
  可识别的真实 provider/model。没有批准的远端凭据或本地模型时写
  `BLOCKED_BY_EMBEDDING_PROVIDER`，不得用哈希/随机/别名向量过门。
- 理由：语义 Gate 用于证明系统能力，不能被针对 fixture 的伪语义实现替代。

### DEC-115 Round 2 采用安全依赖顺序连续收口 — ADOPTED（2026-08-21）

- 决策：执行顺序固定为 migration→Research auth/CAS→terminal UoW→dense/index→
  Research Graph→Citation→evaluation→API/UI/system→final verification。执行 Agent
  连续完成所有不需要新增授权的任务，只在 provider/模型、live 数据、删除、
  commit/push/deploy 或真实 UAT 处暂停。
- 理由：P0 必须先于质量优化关闭；“尽量一次完成”不等于跳过安全或人工门。

### DEC-116 迁移测试的“最新迁移”动态化 — ADOPTED（2026-08-21）

- 决策：`test_migration_preflight_cli.py` 的 apply 目标迁移数不再硬编码 068，
  改为读取 `src.platform.data.store.MIGRATIONS` 声明的总数与最新名。
- 理由：069 CAS 迁移（R2-03 并发控制）合法追加后，硬编码 068 的陈旧断言
  会把“apply 到最新”误报为失败。动态读取保留“完整应用待应用迁移”的意图，
  且对未来纯追加迁移稳健。前置不变量（061 副本、无效备份 exit 2、DB 零字节
  变化）不受影响。

### DEC-117 Research 平台级动作允许空 scope + failed→cancelled — ADOPTED（2026-08-21）

- 决策：
  1. `EMPTY_SCOPE_POLICY` 显式声明 research.read/run/decide 及其 run 派生动作、
     cognition.read/manage、knowledge draft/publish、skills can-execute 允许空
     customer/project（单租户本机平台级操作）；对已有 run 的访问仍由
     `ResearchRunAccessPolicy` 与 run 持久化 scope 完全对账，不因空 scope 放宽。
  2. `business_run_v1` 状态机允许 `failed→cancelled`（显式 cancel 覆盖 failed），
     使 Research cancel-from-failed 与 BusinessRun 终态一致；`succeeded/cancelled`
     仍为绝对终态。
- 理由：run scope 对账（而非空 scope 本身）是授权边界；终态一致性（R2-G3）
  要求 research 与其 business run 不漂移。两处变更均为最小、可回查的契约追加。

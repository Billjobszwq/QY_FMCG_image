# STATUS — TaaS Research RAG & Agent Memory V1

> 状态机：NOT_STARTED / IN_PROGRESS / BLOCKED_BY_* / READY_FOR_UAT / ACCEPTED。
> 本文件只反映 fresh 复核事实与 Task 进度；不得把设计文档快照当作当前值。

## 当前状态

- 总体状态：**`BLOCKED_BY_EMBEDDING_PROVIDER`**。
  Round 2 全部确定性收口完成且 fresh 全绿（R2-02 迁移预检 P0、R2-03 Research
  IAM/scope/CAS P0、R2-04 终态 UoW、R2-05 dense/索引身份、R2-06 Research
  Graph、R2-07 Claim 支持性、R2-08 12 类金标准与分层指标、R2-09 API/UI/
  浏览器/性能/恢复）。唯一未过的是语义召回门 `paraphrase.recall_at_10`
  （0.0 < 0.9）——本机无真实 dense embedding provider，按 DEC-114 诚实
  BLOCKED，不伪造向量。未达 `READY_FOR_UAT`（需 R2-G0→G9 全绿 + 真实 provider）。
- 实施状态：Task 1–7 的主要机器合同完成；Task 8–13 进入 Round 2 收口。
  G6/G7/G8/G9 当前不得标记通过，尚未达到 `READY_FOR_UAT`。
- **Round 2 进度**：R2-01 fresh 基线 DONE。R2-02→R2-09 全部 closed（fresh 绿，
  详见 EXECUTION-LOG 各 R2 条目）：R2-02 迁移预检 P0、R2-03 Research IAM/scope/
  CAS P0、R2-04 终态 UoW、R2-05 dense/索引身份（OpenAI-compatible adapter +
  identity/mismatch fail-closed）、R2-06 Research Graph（typed planner/gap/
  counterevidence/真实冲突/novelty 停止）、R2-07 Claim 支持性（两层验证）、
  R2-08 12 类金标准 + 分层指标 + gold citation + report_hash 可复现、R2-09
  API 行为门（rate/idem/429/409）+ UI + 真实浏览器验收（1024/1280/1440/键盘/
  空态/启动/综合/abstain，无 CoT）+ 性能（p95<2s）+ 恢复/备份演练（mktemp 副本）。
  R2-10 fresh 全量验证完成：**2102 passed, 6 skipped, 6 deselected, 0 failed**；
  前端 lint clean/19 tests/build 成功；live reconcile gate_ok=True；git diff
  --check clean；live DB hash 未变（068）。唯一未过：语义召回门（真实 provider）。
- 完成/发布/训练/生产切换：均未发生，且本轮不授权。
- 全 hermetic 基线：`2034 passed, 6 skipped, 6 deselected, 0 failed`
  （2026-08-21 fresh；自动化回归通过不等于发布 Gate 通过）。
- 前端：`npm run build`（tsc+vite）/ `test` 16 passed / `lint` clean。
- 迁移：live DB **已经应用 062–068**；061 备份在位且 integrity ok。
  旧 CLI “backup guard 晚于自动 schema migration” 的 P0 已在 R2-02 修复
  （用 061 副本红复现→修复→绿）。**未 commit**。
- dense provider：无真实可用（sentence-transformers 等缺失、openai 无
  key）；语义 Gate 在接入真实 provider 前保持
  `BLOCKED_BY_EMBEDDING_PROVIDER`，不得用测试 fake 向量放行。

## 现场基线（fresh 复核，2026-08-21）

| 项目 | 实测值 |
|---|---|
| 唯一开发目录 | `/Users/zhangweiqi/Documents/QY/TaaS by Agent Operation` |
| Branch | `codex/taas-agent-operation-v1`，相对 `origin` ahead 8（未 push） |
| HEAD | `5bbbf89861cc658fdfbb4a7b5b3ad9967e4b6610` |
| tracked 改动 | 8 个 tracked 修改；cognition/governance/research/docs/frontend 等实现文件未跟踪；均未 commit |
| SQLite | `runtime/platform/platform.sqlite`；sha256 `2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109`；size 1470464；`PRAGMA integrity_check = ok` |
| 迁移 | 68 条；最新 `068_cognition_research_report_v1` |
| 061 备份 | `runtime/platform/backups/platform_pre_cognition_20260820T144949Z.sqlite`；sha256 `aef8f09670bbce738f81b15ab49144cf9b5bc686074525f8e517446e2ea4c38e`；integrity ok |
| 表总数 | 128（不含 sqlite_ 内部表）；非零表 14 张（见 EXECUTION-LOG E-1） |
| Agent Manifest（DB） | `agent_manifest_v1 = 0`（Manifest 在进程启动时由 `AgentRegistry._ensure_builtin` seed，当前 DB 未 seed） |
| Agent Definition（DB） | `agent_definition_v1 = 7`（supervisor/modelops/data_steward/survey_agent/analytics_agent/fieldops_agent/finance_agent，均 v1 published） |
| 代码声明 Manifest | `kernel.py _BUILTIN` = 12 个 |
| 记忆/知识/资产 | 旧表仍为现场基线；新增 `cognition_*`、`knowledge_item_version`、`research_*` 表均 0 行 |
| 运行账本 | `business_run_v1=0`、`work_item_v2=0`、`event_envelope_v1=0`、`usage_event_v2=0`、`evidence_bundle_v1=0`、`agent_run_v1=0`、`uat_test_run_v1=0`、`gate_run_v1=0` |
| production bundle | `prod_v4_best_r1`（previous `prod_20260805_v5_r1`）——本轮不切换 |
| 训练进程 | 无（ps 扫描无 ultralytics/train_v1/qlora/finetune/mlx_lm 训练进程） |
| 运行中服务 | orchestrator :8304、label-studio :8300、training monitor :8092（均非本轮启动；平台 API :8400 与 frontend :4173 未运行） |
| 针对性基线测试 | `17 passed, 1 warning in 5.76s`（fresh） |
| 相邻回归 | scope/workflow/evidence/usage 10 个 suite `126 passed in 32.77s`（fresh） |
| 本地资产 | `.superpowers/` 在本仓库不存在（与旧手册不同，按现状处理）；`training-data/`、`recognition-models/`、`runtime/` 实体不进 Git，本轮零触碰 |

## Task 进度（05-IMPLEMENTATION-PLAN-AND-GATES.md）

| Task | 状态 | Gate | 证据 |
|---|---|---|---|
| Task 1 只读基线与禁止行为测试 | DONE | G0 ✅ | EXECUTION-LOG E-6；`tests/cognition/test_live_contract_baseline.py` 13 项绿 |
| Task 2 CognitiveContext 与契约 | DONE | G1 ✅ | E-7/E-8（审查面板 21 项发现全部修复）；`test_context_contracts.py` 绿 |
| Task 3 单一 Agent Definition 投影 | DONE | G2 前置 ✅ | E-9；`tests/governance/test_agent_definition_projection.py` 10 项绿 |
| Task 4 Policy/Alert/Pause | DONE | G2 ✅ | E-10；`test_policy_alert_pause.py` 绿；迁移 062 |
| Task 5 Source/Document/Chunk/Evidence | DONE | G3 ✅ | E-11；`test_source_versioning.py` 16 项绿；迁移 063 |
| Task 6 L1/L2/L3 与旧记忆兼容 | DONE | G4 ✅ | E-12；memory 17 项绿；迁移 064；dry-run 迁移脚本 |
| Task 7 Knowledge/Skill 生命周期 | DONE | G5 ✅ | E-13；23 项绿；迁移 065 |
| Task 8 Index Catalog + ACL-first 检索 | IN_PROGRESS | G6 ❌ | ACL 负例通过；真实 dense provider、完整 index identity、语义 recall 与 p95 未通过 |
| Task 9 Research Graph/预算/恢复 | IN_PROGRESS | G7 ❌ | budget/resume 通过；动态 plan、显式 gap/counterevidence 和真实 conflict 判断未完成 |
| Task 10 Claim 引证与发布 Gate | IN_PROGRESS | G8 ❌ | source/span/scope 校验存在；Claim-support 语义未验证，citation precision 未测量 |
| Task 11 API 与 Research Workbench | IN_PROGRESS | G9 ❌ | Research run API scope 授权 P0 已在 R2-03 关闭；浏览器/rate/idempotency 未闭环 |
| Task 12 固定评测/负例账本/Gate | IN_PROGRESS | G9 ❌ | 框架存在；只覆盖 V1 子集，三项 release gate fresh 失败 |
| Task 13 双读迁移/回滚/收尾 | BLOCKED | G10 未开始 | CLI backup guard 晚于自动 schema migration；前置 Gate 未通过，不能进入正式 UAT |

全量 hermetic 基线：Task 4 后 `1890 passed, 6 skipped, 0 failed`（241s→237s，fresh）。
迁移计数：68。061 备份 integrity ok；live 新表当前为空。不得因此推断可以删除、
回滚或覆盖 live DB。

## 红线核验（每轮更新）

- production bundle 未切换 ✅
- 未启动训练 ✅
- 未 merge/push/deploy ✅
- 未删除/移动/覆盖任何用户数据、模型、SQLite、备份、证据、数据集 ✅
- 当前 live DB 已从 061 变为 068，旧“runtime 零写入”声明失效；Round 2 文档编写未执行 live migration ✅
- 未自行 commit（用户未授权本地 commit）✅

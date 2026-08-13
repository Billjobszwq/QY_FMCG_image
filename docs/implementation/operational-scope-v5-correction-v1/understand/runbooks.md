# Operator procedures: import, quarantine, gate evidence, service lifecycle, READY_FOR_REAL_DATA_UAT protocol (LLM-Image @ HEAD 8e31708d, branch feat/nextgen-training-cycle-v2)

## Key files
- docs/OPERATOR-RUNBOOK.md — 本机运维主 runbook：abos 命令/拓扑/排障/§8 OSV5 口径
- docs/USER-HANDBOOK.md — 角色操作流、Import Center 视图与权限（§11 OSV5）、排障矩阵
- docs/runbook.md — legacy smoke 链路（仅历史回归）+ 监控看门狗 + 只读验证命令
- docs/runbooks/qwen3vl-cascade-local-runbook.md — VLM 级联训练门禁链（preflight/数据集/zero-shot/benchmark/QLoRA/shadow，BLOCKED_BY_ACTIVE_TRAINING 语义）
- bin/abos — 服务控制脚本（status/start/stop/restart/doctor）
- scripts/osv5_gate_evaluate.py — 生成 .eval/scope_v5/gate.json（42 checks）
- scripts/uatv7_rehearsal.py — 生成 UAT V7 证据 uatv7/report.json
- scripts/osv5_browser_evidence.py — 生成浏览器对象级证据 + 截图
- scripts/osv5_gate_negative.py — 12 项负例账本
- scripts/scope_reconcile_imports_v5.py — 历史批次纠偏（bind/quarantine，--apply 幂等）
- scripts/scope_audit_v5.py — 七维只读 scope 审计
- src/platform/gate_evaluator.py — evaluate_gate_from_evidence：READY/BLOCKED_BY_*/STALE 判定（3.2.0）
- src/platform/api/import_api.py — Import Center 全部 HTTP 端点
- src/platform/api/control_plane_api.py — /api/v1/control/gate 实时 freshness 复评
- src/platform/import_center.py — upload/dry_run/commit/preview/list_batches（四视图过滤）
- docs/implementation/agentic-business-os-operational-scope-v5/ — ISSUES.md（P0/P1 台账）/05-GATE-3.2.md/06-UAT-V7-PROTOCOL.md/FINAL-REPORT.md
- .eval/scope_v5/ — gate.json、uatv7/report.json、browser/、gate_negative_tests.json、test_report.json、before/

## Findings
## 1. Service start/stop/restart/doctor — `bin/abos` (唯一入口)

All commands run from project root `/Users/zhangweiqi/Documents/QY/项目/LLM-Image`. Tool: `bin/abos` (bash; idempotent; PID-file/exact-commandline matching only; never starts training; never lies about health — real HTTP probes).

```bash
./bin/abos status    # 四服务健康 + production bundle + 训练进程 + 看门狗（退出码 0=全 UP）
./bin/abos doctor    # Python/DB integrity/dist/端口占用/LLM key/无训练进程
./bin/abos start     # 幂等启动 8091/8092/8300/8400（已在运行则跳过），等待健康探测
./bin/abos stop      # 先停 monitor 看门狗(scripts/monitor_watchdog.sh)，再按 PID/精确命令行停四服务
./bin/abos restart   # stop + start；8400 重启自动执行幂等迁移（sha256 校验，篡改历史迁移拒绝启动）
```

Service topology (OPERATOR-RUNBOOK §1): 8091 `src.recognize.service`（级联识别/production_legacy 后端, log `.platform/logs/recognize.log`）; 8092 `src.training.monitor`（只读监控, `monitor.log`）; 8300 Label Studio SQLite 模式（冷启动最多等 90s, `label_studio.log`）; 8400 `src.composition.serve`（统一 API+Web Shell+Agent Runtime, `app.log`）; 8301 `src.ls_ml_backend.yolo_backend`（可选 ML backend）. 事实源 `.platform/platform.sqlite`（WAL）；production `.models/bundles/CURRENT.json`（只读核验）.

`stop` 注意：必须先停看门狗否则 8092 被自动拉起。红线（§6）：禁止宽泛 `pkill python`、删除 `.platform/`、切换 CURRENT.json、启动训练。真实训练进程存在时 abos 不启停它，需人工按训练门禁处理。

只读核验（§4）：
```bash
sqlite3 .platform/platform.sqlite "PRAGMA integrity_check;"          # ok
sqlite3 .platform/platform.sqlite "SELECT name FROM schema_migrations ORDER BY id DESC LIMIT 3;"
cat .models/bundles/CURRENT.json
./bin/abos status | grep 训练                                         # 必须“无”
python -m src.models.bundle current && python -m src.models.bundle verify --bundle-id <id>
curl -s http://127.0.0.1:8091/v2/health
```

日常对账 API（§7.2，需登录 session cookie）：
```bash
curl -b <登录 cookie> http://127.0.0.1:8400/api/v1/control/reconcile    # consistent=true 才健康
curl -b <登录 cookie> http://127.0.0.1:8400/api/v1/platform/integration # ok=true（Manifest/Agent/命令/UI 路由/OpenAPI）
curl -b <登录 cookie> http://127.0.0.1:8400/api/v1/control/projection   # current 工作投影（可从事件重建）
```

## 2. Import procedures（Import Center，OSV5 口径）

UI 流（USER-HANDBOOK §12）：数据与资产 → Import Center → 下载 14 套 CSV/XLSX 模板 → 上传 → dry-run → 修复错误 → 幂等提交。

HTTP API（src/platform/api/import_api.py，全部需 session + CSRF 写保护）：
- `GET  /api/v1/import/templates` / `GET /api/v1/import/templates/{template_id}/download`
- `POST /api/v1/import/upload`（multipart；同事务写 ExecutionContext：scope/test_run_id/客户关联/授权决定）
- `GET  /api/v1/import/batches?view=operational|mine|history|quarantine`
- `GET  /api/v1/import/batches/{batch_id}`（DTO 白名单，无原始 payload）
- `GET  /api/v1/import/batches/{batch_id}/preview`（原始行预览：仅创建者或 data.import.audit，脱敏 + 50 行上限）
- `POST /api/v1/import/batches/{batch_id}/dry-run`
- `POST /api/v1/import/batches/{batch_id}/commit`（幂等）
- `GET  /api/v1/import/batches/{batch_id}/errors.csv`

权限（USER-HANDBOOK §11 OSV5 增补）：上传需模板对应 capability（客户域=master.manage、IAM=iam.manage、价目卡=finance.manage、问卷=survey.manage）；批次涉及的**每个客户**都必须在授权范围内，任一客户无权**整批拒绝**（fail-closed）；read_only 不能上传/预检/提交。四个视图：运营导入（默认，仅 effective operational）/我的批次/Test Run 历史证据（需授权）/隔离待处理（管理员/审计）。

## 3. Quarantine handling（隔离）

- 隔离态定义：`src/platform/scope.py` data_scope ∈ {operational, uat_fixture, history, archived, quarantine}；quarantine = 非运营隔离态，不可唯一归属的历史批次 fail-closed 落此，不得删除、不得继续计入运营。
- 纠偏脚本（OPERATOR-RUNBOOK §8）：
```bash
python3 scripts/scope_reconcile_imports_v5.py          # 只读 plan（先看分类）
python3 scripts/scope_reconcile_imports_v5.py --apply  # 执行纠偏（幂等；逐批审计入账 scope_backfill_audit_v1）
```
证据优先级：mapping_json 行内 customer_id ↔ uat_test_run_v1.customer_ids_json → commit receipts 业务对象父链 → 创建时间窗（仅辅助）。能唯一归属 Test Run → 追加式绑定 uat_fixture + test_run_id + visibility=history（不删行）；不能唯一归属 → data_scope='quarantine'。
- 裁决协议（OSV5 FINAL-REPORT §52）：隔离区批次由管理员人工裁决——**保持隔离**或**删除需走审批矩阵 `data.delete`**（高风险动作人工批准）。当前无专用裁决 API/状态机（属待办工作项）。
- 日常审计：`python3 scripts/scope_audit_v5.py`（只读；列/创建/scanner/archiver/API/Gate/Registry 七维；取代 scope_audit_v4）。

## 4. Gate evaluation — 证据再生成脚本映射（OSV5，Gate 3.2.0）

| 证据 | 生成脚本（准确命令） | 输出 |
|---|---|---|
| Gate 主文件 | `python3 scripts/osv5_gate_evaluate.py` | `.eval/scope_v5/gate.json`（42 checks，禁止手改） |
| UAT 证据 | `python3 scripts/uatv7_rehearsal.py` | `.eval/scope_v5/uatv7/report.json`（真实 multipart Import API；23 项检查；含服务重启稳定性） |
| 浏览器证据 | `python3 scripts/osv5_browser_evidence.py` | `.eval/scope_v5/browser/browser_evidence.json` + 28 张 PNG（需 8400 运行、真实浏览器角色 owner/read_only/auditor） |
| 负例账本 | `python3 scripts/osv5_gate_negative.py` | `.eval/scope_v5/gate_negative_tests.json`（12 项负例必须全部 ALL_BLOCKED=True） |
| 测试报告 | hermetic pytest 运行后入账 `.eval/scope_v5/test_report.json`（手写摘要 JSON，非脚本自动生成）；命令：`/Users/zhangweiqi/miniconda3/bin/python3 -m pytest tests -q -p no:cacheprovider`（marker `not host_mps`）；host MPS 单跑 `-m host_mps` | `.eval/scope_v5/test_report.json` |
| P0/P1 台账 | 手工维护 markdown：`docs/implementation/agentic-business-os-operational-scope-v5/ISSUES.md`（Gate `no_open_p0_p1` 消费；有 open P0 → BLOCKED_BY_P0，open P1 → BLOCKED_BY_P1） | — |

`osv5_gate_evaluate.py` 绑定：HEAD / 代码树 hash(src/platform,web/src,scripts) / migration hash / DB scope-graph fingerprint / 事件与 outbox 水位 / work 投影 hash / 关键表计数；要求 tracked worktree clean。评估后 `GET /api/v1/control/gate`（src/platform/api/control_plane_api.py → `evaluate_gate_from_evidence`）以 gate.json 为基准做**实时 freshness 复评**：DB/代码变化 → STALE_GATE_EVIDENCE。

文档化执行顺序（EXECUTION-LOG T5→T10）：reconcile imports → gate 初评+negative → UAT V7 → browser → 全量回归(test_report) → **最终 Gate 必须在收尾 HEAD 上重新生成**（Gate 永远最后跑）。

历史脚本（si2/si3/si4_*、uatv4/v5/v6_rehearsal、v3_uat_rehearsal*、scope_audit_v3/v4）为被取代的前代口径，勿用。`docs/runbook.md` 的 8090 链路为 legacy（仅历史回归，禁止生产）。

## 5. READY_FOR_REAL_DATA_UAT vs BLOCKED_BY_* 协议

- **只许机器生成，禁止手写**（"机器评估，非手写"）。状态由 `src/platform/gate_evaluator.py::evaluate_gate_from_evidence`（EVALUATOR_VERSION="3.2.0" 单点定义，全链引用）计算。
- READY_FOR_REAL_DATA_UAT = 42 检查全绿（含：证据绑定当前 HEAD+树 hash+迁移 hash、worktree clean、fixture 零泄漏、scope lineage 完整、Registry 全覆盖可执行、IAM/BI/Import effective 口径一致、UAT/browser/test 证据齐全且通过、ISSUES 无 open P0/P1、services_healthy、sqlite_integrity、no_training_process、current_bundle 未变）。
- 任一检查失败 → 具体 `BLOCKED_BY_*` 码；判定优先级：**STALE > 浏览器语义 > scope lineage > fixture 泄漏 > …** 现存阻断码族：STALE_GATE_EVIDENCE, BLOCKED_BY_GATE_EVIDENCE / _SCOPE_LINEAGE / _IMPORT_SCOPE_LINEAGE / _SCOPE_REGISTRY / _UAT_FIXTURE_PROJECTION / _UAT_FIXTURE_POLLUTION / _IAM_IDENTITY / _BI_EFFECTIVE / _BROWSER_SEMANTICS / _STATE_PROJECTION / _AGENT_FAILURE_LINEAGE / _P0 / _P1。
- STALE 处理协议：任何代码/DB 变化后旧 Gate 即失效 → 修完问题后按上表**重新生成证据链**（test/UAT/browser/issues），最后在干净 worktree 的当前 HEAD 上重跑 `osv5_gate_evaluate.py`。
- READY **只表示"可以开始真实数据 UAT"**；没有用户真实客户/地址/问卷贯穿验收 + 人工验收，不得写 ACCEPTED/PRODUCTION_READY。用户下一步（FINAL-REPORT §52）：真实数据走 Import Center 运营视图 UAT + 人工走查四视图/BI/IAM/Gate 区块 + 隔离区人工裁决。
- 训练链（qwen3vl runbook）的 BLOCKED_BY_ACTIVE_TRAINING 语义：等待训练自然结束并完成 G-CURRENT 对账，不得绕过；exit 码约定 `run_cascade_shadow_eval --mode run`：2=active training、3=未授权、4=G-APPLE 未通过。

## 6. 冷启动/登录（USER-HANDBOOK §1）

```bash
cd /Users/zhangweiqi/Documents/QY/项目/LLM-Image
./bin/abos doctor && ./bin/abos start && ./bin/abos status   # 四服务 UP
# 打开 http://127.0.0.1:8400，登录 bill（凭据已数据库锁定，触发器拒绝 UPDATE/DELETE）
```


## Risks
- Gate 强依赖 tracked worktree clean（tracked_worktree_clean check → BLOCKED_BY_GATE_EVIDENCE）：任何未提交改动立即阻断 READY；再生成证据前必须先 commit 或 stash
- test_report.json 为手写摘要、ISSUES.md 为手工 markdown 表格被 gate 解析（_open_issues）——两者都是非机器绑定的证据面，存在漂移/漏判风险（与待办'报告单一事实源'一致）
- quarantine 写入路径被标记为存在写逃逸（待办 P0-1 '隔离写逃逸修复'未开始）——在修复前隔离态不是完全 fail-closed
- 隔离批次删除必须走审批矩阵 data.delete，但手册未写明确切批准入口路径，操作员易误用直接 SQL/删行（红线禁止）
- OPERATOR-RUNBOOK §3 冷启动写 admin 登录用 .env PLATFORM_ADMIN_PASSWORD，而 USER-HANDBOOK §1 写凭据为 PLATFORM_ADMIN_CREDENTIALS 且已数据库锁定——两处文档口径不一致（文档漂移）
- 前代脚本（si2/si3/si4_*、uatv4-v6、scope_audit_v3/v4）仍在 scripts/ 下，命名近似易被误用生成过期口径证据
- osv5_browser_evidence.py 与 uatv7_rehearsal.py 需要 8400 在线（真实 HTTP），运行顺序错误（先 gate 后 UAT/browser）会产生立即 STALE 的 gate.json

## Open questions
- test_report.json 无自动生成脚本——是 hermetic pytest 后手工入账的摘要 JSON；再生成流程的准确命令/包装未在 runbook 明文（推测为 miniconda python -m pytest tests -q -p no:cacheprovider，marker 过滤 host_mps）
- 隔离区人工裁决目前无专用 API/状态机；'保持隔离或删除(data.delete 审批)'的具体 UI/命令路径未在手册中写成操作节
- bin/abos start 后 /api/v1/control/gate 与离线 gate.json 的一致性以实时复评为准，但 runbook 未给出该端点的无 cookie 冒烟命令
- docs/runbooks/ 仅有 qwen3vl 一份；OSV5 证据再生成顺序未固化成独立 runbook 文件（只散见 EXECUTION-LOG/FINAL-REPORT）
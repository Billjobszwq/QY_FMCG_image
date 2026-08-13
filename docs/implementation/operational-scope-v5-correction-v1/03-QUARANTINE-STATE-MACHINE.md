# 03-QUARANTINE-STATE-MACHINE — 隔离区人工裁决闭环（C-3）

## 1. 状态机

```
                ┌───────────────────────┐
                │      quarantined      │（初始：data_scope=quarantine 的批次）
                └───────────┬───────────┘
       ┌──────────────┬─────┴──────┬─────────────────┐
       ▼              ▼            ▼                 ▼
retained_for_    bound_to_     soft_          release_requested
evidence         test_run      discarded            │
（继续隔离留证）（绑定 Test Run）（软作废）      ┌──────┴───────┐
                                               ▼              ▼
                                       release_approved   拒绝→回 quarantined
                                               │
                                               ▼
                              创建新批次 revision（operational）
                              原批次 → superseded_by_new_batch
```

- 终态：soft_discarded、release_approved（伴随 superseded_by_new_batch）、bound_to_test_run（批次转 uat_fixture 并绑定 test_run，走新 revision 或审计绑定——实现取“新 revision 绑定”保持原行不动）。
- 所有迁移幂等、CAS 保护；原始导入证据（import_batch_v1 既有行、mapping/dry_run/commit JSON、既有 evidence/audit）不可修改。

## 2. 存储（迁移 060_quarantine_adjudication_v1）

```sql
CREATE TABLE quarantine_adjudication_v1 (
  batch_id TEXT PRIMARY KEY REFERENCES import_batch_v1(batch_id),
  state TEXT NOT NULL DEFAULT 'quarantined',
  version INTEGER NOT NULL DEFAULT 0,
  target_test_run_id TEXT NOT NULL DEFAULT '',
  revision_batch_id TEXT NOT NULL DEFAULT '',
  requested_by TEXT NOT NULL DEFAULT '', requested_at TEXT NOT NULL DEFAULT '',
  approved_by  TEXT NOT NULL DEFAULT '', approved_at  TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
-- 迁移同时为三个现存 quarantine 批次初始化 state='quarantined', version=0（幂等 INSERT OR IGNORE）

CREATE TABLE quarantine_adjudication_evidence_v1 (   -- 只读分析产物，追加式
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
-- 触发器：禁 UPDATE/DELETE（两张表均禁；adjudication 主表允许 UPDATE 仅限 CAS 路径——
-- 因此主表只加 NO DELETE 触发器，UPDATE 靠 CAS WHERE version=? 约束）
```

## 3. API（POST /api/v1/import/batches/{batch_id}/adjudication）

Body：`{action, reason?, target_test_run_id?}`；action 枚举与规则：

| action | 允许前态 | 权限 | 效果 |
|---|---|---|---|
| retain | quarantined/* | data.import.audit 或 platform | state=retained_for_evidence（可反复，幂等） |
| bind_test_run | quarantined/retained | platform（master.manage） | 校验 target_test_run 存在且 current/archived 合法 → 创建新批次 revision（data_scope=uat_fixture + test_run_id），原批次 state=bound_to_test_run |
| soft_discard | quarantined/retained | platform | state=soft_discarded（批次行不动；列表显示软作废） |
| request_release | quarantined/retained | platform | state=release_requested，记录 requested_by/at |
| approve_release | release_requested | platform，且 actor ≠ requested_by | 双人审批通过 → 创建新批次 revision（data_scope=operational，复制 mapping 行，走标准 upload→dry-run→commit 生命周期），原批次 state=release_approved→superseded_by_new_batch |
| reject_release | release_requested | platform | 回 quarantined，记录 reason |

- 每次成功迁移：iam.audit `import.quarantine.<action>` + version+1 + quarantine_adjudication_evidence_v1 追加一行。
- CAS：`UPDATE quarantine_adjudication_v1 SET ... WHERE batch_id=? AND version=?`；rowcount=0 → 409 `ADJUDICATION_VERSION_CONFLICT`。重复提交相同目标态 → 200 幂等返回当前态。
- 申请人自批 → 409 `ADJUDICATION_SAME_ACTOR`。
- 非 quarantine 批次调用 → 409 `ADJUDICATION_NOT_QUARANTINE`。
- 跨客户/无权限 → 403（沿用 authorize_batch + visible_customers fail-closed）。

## 4. 新批次 revision 语义

- revision 为新 batch_id（`imp-` 前缀），source='quarantine_release'，correlation_id=原 batch_id；
- mapping_json 复制自原批次（原始文件行的副本），data_scope 按动作设定；
- 原 quarantine 行保持 quarantine 永不可写（C-1 守卫），仅裁决表 state 变更；
- supersedes 关系：revision 行 correlation_id + 裁决表 revision_batch_id 双向可查。

## 5. UI（ImportCenter 隔离视图）

- 详情卡片在 C-1 禁写横幅下渲染裁决按钮组（按 state/权限显隐）：继续隔离留证 / 绑定 Test Run（输入/选择 test_run）/ 软作废 / 申请转正式 /（审批人视角）批准·拒绝转正式；
- 每个动作前确认对话框；动作后刷新详情与裁决历史（读 quarantine_adjudication_evidence_v1）；
- 三个现存批次（imp-8e4f53455eaa、imp-9a8028ec9733、imp-bf333d101db6）必须可在 UI 安全查看与裁决。

## 6. 负例（进 tests/platform/test_osv51_quarantine_adjudication.py）

无权限 403；跨客户 403/404 fail-closed；直接 URL 访问无权批次拒绝；并发双批准仅一个成功（另一 409）；自批 409；非法状态迁移（如 quarantined 直接 approve）409；重启后状态不丢。

# 02-IAM-TEST-IDENTITY-LIFECYCLE · IAM 测试身份生命周期

## 1. 数据模型（迁移 057）

`iam_principal_v1` 追加列（追加式，不动历史行）：
- `data_scope TEXT NOT NULL DEFAULT 'operational'`
- `test_run_id TEXT NOT NULL DEFAULT ''`
- `origin TEXT NOT NULL DEFAULT 'manual'`（manual/uat/system）
- `visibility TEXT NOT NULL DEFAULT 'current'`（current/history）
- `archived_at TEXT NOT NULL DEFAULT ''`
- `disabled_reason TEXT NOT NULL DEFAULT ''`

`iam_membership_v1` 追加列：
- `data_scope`、`test_run_id`、`visibility`、`archived_at`

事实源选择：**结构化 provenance 列**（DEC-SI4-001）；登录、授权、
列表、统计统一消费这些列，禁止平行 ledger。

## 2. 创建（受信路径）

- `POST /api/v1/iam/principals` 接受 `test_run_id`：非空时先过
  `assert_test_run_current`（存在/current/客户匹配，fail-closed），
  同事务写 data_scope=uat_fixture + test_run_id + origin=uat。
- UAT driver 创建六角色时必须携带 test_run_id。
- 无 test_run 的普通创建 = operational（真实身份）。

## 3. 登录与授权

- 登录：principal.status != 'active' 或 visibility='history' 或
  data_scope fixture 且 test_run 已归档 → 拒绝，稳定错误码
  `IDENTITY_ARCHIVED`（403/401），写 `iam_audit_event_v1`。
- 会话：归档事务删除（注销）该 principal 的全部 auth_sessions
  属于"安全失效"，不属于删历史（会话是运行时态）；principal/
  membership 行保留。
- 授权模拟器/权限矩阵只读 operational membership。

## 4. Test Run 归档事务（archive_namespace 扩展）

同一事务收敛：
1. principal：status='disabled'、visibility='history'、
   archived_at、disabled_reason='test_run_archived'
2. membership：visibility='history'、archived_at
3. auth_sessions：该 principal 全部会话 DELETE（运行时态失效）
4. test_run 上下文置 archived（既有逻辑）
5. 写 iam_audit_event_v1 归档事件（actor/test_run/数量）

归档后不变量：
- active UAT principals = 0
- operational UAT memberships = 0
- archived UAT identity 登录成功 = 0

## 5. 历史收敛（一次性，审计）

存量 85 账号按已登记 Test Run registry 回绑 provenance：
username 含已登记 namespace → 绑定该 test_run；随后统一执行归档
事务。回绑规则写 `scope_backfill_audit_v1`（SI4 r20+）。
历史 principal/membership 行永不物理删除。

## 6. 界面

- 正常"账号与角色"：默认 operational；搜索/分页/状态筛选/角色筛选；
  fixture 仅测试与证据中心可见（含 test_run/归档时间/角色/客户）。
- 不提供"重新启用测试账号"快捷操作。

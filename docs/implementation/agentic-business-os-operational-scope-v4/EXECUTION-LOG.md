# EXECUTION-LOG · Operational Scope V4

## T0（2026-08-13 01:xx–02:xx）

1. 现场：开工实际 HEAD `63679be0`；检测到外部 TaaS commits
   （2b22b519/4bb0d49f/805fc796/cff57e1c/63679be0），diff 审计仅
   docs/promotion + tests/promotion，与 scope 链无交集。
2. 独立审计 scripts/scope_audit_v4.py 复现全部问题：
   - IAM：85 active UAT principals / 97 memberships（全带客户授权）
     / 85 会话未失效；运营 IAM 页直接显示
   - BI：data-products 物理行数（37/25/22/25/50/195/24/20）vs 运营
     API 0；8 UAT metrics、9 dashboards、1+ reports 滞留运营面
   - 前端：7 处硬编码测试客户（BI/Finance/Geo/Usage）
   - Registry：物理覆盖 100% 但无生命周期语义（分类逃逸）
   - Gate：V3 绑定 78f2e990 已 STALE（freshness 机制正常）
3. 备份：platform_pre_scope_v4_20260813T023659.sqlite（sha256
   e886123f…；双向 integrity ok）。
4. Gate 降级投影 .eval/scope_v4/gate.json
   （BLOCKED_BY_OPERATIONAL_FIXTURE_SURFACE）。
5. 治理目录 16 件落盘；提交 6121353f。

## T1（红测试）
tests/platform/test_si4_operational_surface.py 15 项全红；提交
fe7a543c。

## T2–T5（实现 + live 收敛）
- 迁移 057（IAM provenance）、058（BI/import lifecycle）
- IAMService：create/grant/list/verify_login 全链 provenance；
  auth.login IDENTITY_ARCHIVED 上抛
- analytics：bi_effective_counts 唯一口径；metric/dashboard
  provenance + 运营目录过滤
- finance：generate_invoice effective 过滤 + invoice 继承客户
  provenance；账单行随账单归档
- Registry：LIFECYCLE_KEYS 七项声明（分类默认 + 敏感表专项）
- 前端：useOperationalCustomer + CustomerPicker（BI/Usage/Finance/Geo）
- live 收敛（scope_backfill_v3.py r20–r23，全部审计入账）：
  - r20/r21：85 principals 回绑+禁用，97 memberships 归档，会话失效
    （含顺序 bug 修复补执行）
  - r22：8 UAT metrics 归档
  - r23：9 dashboards + UAT 客户报表归档（含 uat-cust-a demo 看板）
- 提交 9fd80c7c / 705024ec / f83aeb99。

## T7（UAT V6）
scripts/uatv6_rehearsal.py：57/57 首跑通过；ids 30/30 非空；
validator problems=[]；含归档后登录拒绝 6/6、IAM 页干净、历史保留、
泄漏注入 freshness 闭环。提交 b1dded1c。

## T6/T8（Gate 3.1 + 浏览器）
- gate_evaluator：IAM/BI/Finance 检查 + browser_routes_covered（12）
  + 新 BLOCKED 状态
- scripts/si4_browser_evidence.py：12 页 × 四视口 30 断言全过，
  console unexplained=0；浮层窄屏适配；IAM 列表搜索/筛选/分页
- 负例 22 项 .eval/scope_v4/gate_negative_tests.json
- 提交 a4fb3f7f。

## T9/T10（收尾）
- hermetic 1447 passed / host MPS 6 / typecheck 干净 / build 成功
- si4_gate_evaluate.py 全量评估 → READY_FOR_REAL_DATA_UAT
  （34 检查 0 失败）；/control/gate 实时复评一致
- FINAL-REPORT（47 项）、handbook 更新；收尾提交。

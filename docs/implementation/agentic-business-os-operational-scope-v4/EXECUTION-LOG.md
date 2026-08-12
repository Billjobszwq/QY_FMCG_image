# EXECUTION-LOG · Operational Scope V4

## T0（2026-08-13 02:2x–03:0x）

1. 现场：开工 HEAD `63679be0`（复核期间检测到外部 TaaS commits：
   2b22b519/4bb0d49f/805fc796/cff57e1c/63679be0，diff 仅
   docs/promotion + tests/promotion，与 scope 链无交集，已审计记录）。
2. 服务：8091/8092/8300/8400 UP；integrity ok；CURRENT=
   prod_v4_best_r1；训练进程=0。
3. 备份：platform_pre_scope_v4_20260813T023659.sqlite（SQLite backup
   API；双向 integrity ok；sha256 e886123f96ba…）。
4. 独立审计 scripts/scope_audit_v4.py 复现全部问题：
   - IAM：85 active UAT principal / 97 membership（全带客户授权）/
     85 auth_sessions / uatv5 五角色 active
   - BI：data-products 物理 37/25/22/25/50/195/24/20 vs effective
     0/0/0/2/18/…；bi_metric_v1 8+ UAT 指标无 scope 列；
     bi_dashboard_v1 无 scope 列
   - 前端：7 处硬编码测试客户（BIWorkbench/UsageWorkbench/Finance/Geo）
   - Gate：V3 gate 绑定 78f2e990 已 STALE（freshness 正常工作）
   - 新发现：import_batch_v1 无 scope 列（20 条 UAT 批次）→ SI4-011
5. Gate 降级投影 .eval/scope_v4/gate.json（mtime 最新被
   /control/gate 选中）。
6. 治理目录 16 件落盘；提交 si4(T0)。

## T1+ （持续更新）

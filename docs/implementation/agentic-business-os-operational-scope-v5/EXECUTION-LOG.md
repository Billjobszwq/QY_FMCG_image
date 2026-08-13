# EXECUTION-LOG · Operational Scope V5

## T0（2026-08-13 12:3x–13:0x）

1. 基线核对：HEAD=6ec99985、branch=feat/nextgen-training-cycle-v2、
   四服务 UP、production=prod_v4_best_r1、训练进程=0、integrity=ok、
   live gate=READY_FOR_REAL_DATA_UAT（evaluator_version=3.0.0）——
   与指令第一节全一致，无差异。
2. 独立复现（scripts/scope_audit_v5_before.py，只读，防覆盖）：
   - P0-001：SQL total=20/operational=20/uat_semantic=20；
     /import/batches count=20；data-products import.batches_v1=20
   - P0-002：upload/_save_batch 签名无 test_run_id（inspect 事实）
   - P0-004：详情响应 returns_mapping_json/dry_run_json/
     error_report_json/commit_json 全 true
   - P0-005：125/23/18 三套平行清单；import_batch_v1 未进
     scanner/archiver
   - P0-006：35 假 pk / 5 假 customer_col（含 import_batch_v1.
     customer_id）/ 115 假 tenant_col
   - P1-004：文档 Gate 3.1 vs 代码 3.0.0
   - 证据：.eval/scope_v5/before/before_audit_v5.json
3. 备份：platform_pre_scope_v5_20260813T124408.sqlite（备份库
   sha256 f1f92091…；双向 integrity ok）。
4. Gate 降级：随 Gate 3.2 检查实现由真实 evaluator 生成
   .eval/scope_v5/gate.json（见 T6 段，不手写状态）。

## T1（红测试）

tests/platform/test_osv5_import_scope.py：32 项断言。首跑
27 failed / 5 passed；5 个"绿"均为诚实登记：
- r06（operational 不携带 test_run）：当前默认行为恰好满足；
- r12/r13：read_only dry-run/commit 恰被状态机 409 拦下（403 未
  实现，修复后转真绿）；
- r24/r28：parent edge 现状恰好可解析 / coverage 已捕获未登记表。
红态证据：本文件首跑记录（未修复前不得再跑覆盖语义）。

## T2–T3（批次执行上下文 + IAM/DTO）

- 迁移 059：import_batch_v1 生命周期列 + import_batch_customer_scope_v1。
- ImportCenter：TEMPLATE_SCOPE 矩阵 + authorize_template/customers/
  batch（整批 fail-closed）；upload(test_run_id) 同事务 uat_fixture；
  batch_dto 白名单 + preview_rows 脱敏；list_batches 四视图；
  dry-run/commit 归档守卫 + fixture 作用域继承（自然键/回执键）。
- import_api：全端点 IAM 接入；errors.csv/preview 授权。
- IAM：finance.manage/data.import.audit scope + auditor 角色。

## T4/T6/T9（可执行 Registry + Gate 3.2 + session）

- scope_registry：35 假 pk/5 假 customer_col/115 幻影 tenant_col
  全部修正；validate_registry；ARCHIVE_HANDLERS（20 表）+
  archivable_tables/leak_scan_tables/archive_handler_for。
- scope.py/test_data.py：_SCOPED_TABLES/_SCOPED_DOMAIN_TABLES 改
  Registry 派生；archive_namespace 由 handler 执行。
- gate_evaluator：3.2.0；18 新检查；BLOCKED_BY_IMPORT_SCOPE_LINEAGE；
  data_products_all_effective_consistent 8 产品逐项。
- auth：purge_expired_sessions（登录触发/只删过期/审计/bill 豁免）。

## T5（历史 20 条纠偏，live）

plan（只读）：20 条 → 17 bind（uat_fixture_v3/uatv2/uatv3 唯一客户集
匹配）+ 3 quarantine（uat-cust-a/b、uatv2 l16gw2 无登记 Test Run）。
apply：幂等 + 20 行 scope_backfill_audit_v1；operational 20 → 0。

## T6（Gate 3.2 降级 + 负例）

osv5_gate_evaluate.py：42 检查，首次评估 BLOCKED_BY_P0（诚实降级，
非手写）；osv5_gate_negative.py：12 负例 ALL_BLOCKED=True。

## T7（UAT V7）

uatv7_rehearsal.py：首跑 23/23（validator problems=[]；ids 6 新键；
current_bundle=prod_v4_best_r1；training=0；residue=0）。首次运行
前的一次脚本调试遗留 namespace 已归档（诚实登记）。

## T8（浏览器对象级验收）

osv5_browser_evidence.py：29/29；console unexplained=0；28 截图
hash 入账。修复三处工具缺陷（falsy 值吞噬/status 测试中心区块/
同 URL hash 导航状态污染）并在脚本内注释留痕。前端 ImportCenter
重构（四视图 + 全字段列）。

## T9（全量回归）

hermetic 1479 passed/1 skipped/6 deselected（基线 1447 + 新 32）；
host MPS 6 passed；tsc 零错误；vite build 成功；git diff --check 干净；
live integrity ok；doctor 四端口在用/训练进程无；test_report.json
入账。

## T10（收口）

ISSUES 全 CLOSED；STATUS/LIST 全 DONE；FINAL-REPORT 53 项；
handbook 新增 V5 九条方法论 + 变更记录；USER-HANDBOOK §11 /
OPERATOR-RUNBOOK §8 / MODULE-AGENT-DEV-GUIDE §9 增补；最终 Gate
在收尾 HEAD 上由真实 evaluator 生成（.eval/scope_v5/gate.json）。

---

## 附录 V5.1 更正（2026-08-13）

T6 条目中“42 checks”为当时真值；T8/T10 后 gate.json 实际 52 checks。
OSV51 轮（docs/implementation/operational-scope-v5-correction-v1/）
已建立 machine_facts.json 机器事实源：Gate checks 数、Registry 数、
UAT namespace/批次 ID、测试计数一律机器读取，禁止手工录入。

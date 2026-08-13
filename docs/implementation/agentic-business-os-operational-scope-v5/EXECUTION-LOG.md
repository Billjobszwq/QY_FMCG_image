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

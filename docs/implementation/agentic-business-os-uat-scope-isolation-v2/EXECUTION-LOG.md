# EXECUTION-LOG · UAT Scope Isolation V2

## T0（2026-08-12）

1. Git 核对：HEAD=9f3554e7、分支=feat/nextgen-training-cycle-v2，
   tracked 干净（与指令预期一致）。
2. `./bin/abos status`：recognize/monitor/label_studio/app 全 UP；
   production=prod_v4_best_r1；训练进程=无。
3. 模型 hash：detector.pt sha256=84bf9936…554975（与预期一致）。
4. DB：integrity ok；50 migrations；fixture 统计见 00-LIVE-AUDIT。
5. 备份：.platform/backups/platform_pre_scope_v2_20260812202343.sqlite
   （integrity ok，sha256=7d65b1ce…3a41c）。
6. 复现 P0-001/P0-002/P1-001..004/P2-001..003（证据在 00-LIVE-AUDIT
   与 ISSUES.md）。
7. Gate 降级投影：写入 .eval/uat_scope_v2/gate.json =
   BLOCKED_BY_UAT_FIXTURE_PROJECTION（旧 gate.json 保留）。
8. 建立治理文档：AGENT-EXECUTION-PROMPT/00/01/02/03/04/STATUS/
   ISSUES/DECISIONS/LIST/EXECUTION-LOG/FINAL-REPORT/READING-LIST。

最近 30 commits（git log --oneline -30）：
9f3554e7 ufc(final) / 6664022f ufc(T9/T10c) / 16629042 feat brand /
8beb2695、2590dc88 docs TaaS / 53022a54 ufc(T10b) / 4d157035 feat
三受众 / b9a1723e ufc(T10a UAT V3 driver) / 9ef9a022、5eb69088 docs /
803e9342 ufc(T7,T8) / 9900ac33 ufc(T4 fixture isolation 049) /
0e0905f8 ufc(T1-T3,T5,T6,T9) / 98ce420f、efd96fa1、21326f47、96e5354c
docs / 99e2ca5f ufc(T0) / 6cbca9c0 uatcc(T8-final) / 0f447e81、
22142f5f uatcc(T8) / 4e9bcc2f uatcc(T7) / 33bd4bcb uatcc(T4) /
50398320 uatcc(T5) / 98653f31 uatcc(T6) / ecd03ffa uatcc(T0.5) /
1de259aa uatcc(T3) / e0a478d3 uatcc(T2) / bd56676e uatcc(T1) /
f44c0f76 uatcc(T0)。

（后续阶段按 T1..T10 追加。）

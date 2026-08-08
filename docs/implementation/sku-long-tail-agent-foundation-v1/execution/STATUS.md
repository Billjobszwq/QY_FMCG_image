# STATUS

| 项 | 值（2026-08-09） |
|---|---|
| 分支/HEAD | feat/nextgen-training-cycle-v2 @ e95e3ca |
| Gate | AUDIT_VERIFIED → 进入 CRITICAL_TRAINING_BUGS_FIXED |
| SAM 进程 | 两进程自然完成，对账通过；SOURCE_SNAPSHOT_UNPROVABLE |
| 测试基线 | 待本轮红测试后更新 |
| production | prod_20260805_v5_r1 未切换 |

## 2026-08-09 收口
- Gate = **FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_EVALUATION**
  （缺独立人工真值，禁写 PROMOTION_READY / COMPLETE）。
- 四 Lane 均有真实实验 artifact（M1/M2 smoke、M3 random+grouped、M4 pilot、
  SAM decoder v1/v2 实验）；证据级诚实（pseudo/user_labeled/demo）。
- 未关闭：KB 覆盖 0（百事系）→ 需扩 KB；45 pending 类待业务裁决；
  demo_micro_gold_v1（120–300 region）待人工；组合并发 benchmark 未实测。

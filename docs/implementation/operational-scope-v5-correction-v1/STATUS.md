# Operational Scope V5.1 Correction — STATUS

- 轮次：operational-scope-v5-correction-v1
- 基线 branch：feat/nextgen-training-cycle-v2
- 基线 HEAD：8e31708d584459fb38fedefe21b070bede36db57
- 当前 HEAD：46057d2875a3538c5917bf2aebd66a9f1d28e6f7（代码冻结）
- production：prod_v4_best_r1（未切换，本轮禁止切换）
- 评估器版本：3.2.0 → 3.3.0（单点定义）
- 负例账本：12 → 21（全部 ALL_BLOCKED）
- DB 备份：.platform/backups/platform_pre_osv51_correction_20260813T162315.sqlite（integrity ok）

## 阶段状态

| 阶段 | 状态 | 证据 |
|---|---|---|
| 开工基线 | DONE | BEFORE-STATE.md + before-snapshots/ |
| P0-1 quarantine 写逃逸 | DONE | test_osv51_quarantine_guard.py 52 绿；负例 13/14/16；QA_REPLAY_DETECTED 入账 |
| P0-2 首次密码零持久化 | DONE | test_osv51_password_zeropersist.py 10 绿；负例 15；live DB scrub 0 命中 |
| P1 隔离区裁决状态机 | DONE | test_osv51_quarantine_adjudication.py 15 绿；迁移 060 live 应用；3 批次 retained_for_evidence |
| P1 17 批血缘回填 | DONE | test_osv51_lineage_backfill.py 9 绿；12→29 关联行；3 quarantine 待裁决 |
| P1 parallel timeout 竞态 | DONE | 确定性测试 + 100 轮压力零漂移（3 复跑 + 150 轮异种子） |
| P0 Gate 证据新鲜度 | DONE（证据链重生成中） | binding 块/去自比较/实时复核/负例 17-21/12 项测试绿 |
| P2 导航滚动连续性 | DONE（浏览器 QA 中） | ScrollManager + 四视口断言入浏览器证据 |
| P1 报告单一事实源 | DONE | machine_facts.py + V5 更正附录 |
| 完整验收 | 进行中 | 全量 1580 中 1 failed → 定位修复后重跑，未绿不得 READY |

## 当前判定

BLOCKED_BY_TESTS（全量存在 1 失败，正在定位）——不得宣称
READY_FOR_REAL_DATA_UAT / ACCEPTED / COMPLETE / PRODUCTION_READY。

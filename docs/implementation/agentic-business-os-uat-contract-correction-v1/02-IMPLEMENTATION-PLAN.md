# 02 · 实施计划

| 阶段 | 内容 | 交付物 |
|---|---|---|
| T0 | 现场复核 + 10 红测试 | 00-LIVE-AUDIT.md、test_uatcc_red_contracts.py（RED） |
| T1 | 照片题/门头必拍契约 | migration 047（media 角色/状态列）；survey lint/submit/attach_media 契约；Builder/填写页 UI；浏览器 5 步证据 |
| T2 | Agent 统一链 | invoke 创建 BusinessRun/Work/Evidence；usage 挂链；历史 attribution 账本；财务 UI 下钻+历史未归属标识 |
| T3 | 真实并行 | workflow_branch_v1；线程池有界并行；join all/any/quorum；重启恢复；wall-time 证明 |
| T4 | UAT V2 | scripts/v3_uat_rehearsal_v2.py（唯一 namespace、六角色、真照片、全实体、validator 强制） |
| T5 | shadow 纠偏 | extract_products(sku_name)；hash 记录；selected-failure smoke + 负样本 + 延迟 p50/p95 + rollback smoke；`USER_SELECTED_UAT_MODEL` |
| T6 | rate limit | rate_limit_v1 表 + 中间件（登录/Agent/导入/识别/BI/工作流/切模）；429+Retry-After+审计；管理端点 |
| T7 | 浏览器验收 | 16 页 ×（1440/1280/1024/768）；console=0；截图命名归档 |
| T8 | 全量验证 | hermetic+host_mps+tsc+build+integrity+migration 幂等+四方对账+服务恢复+安全+限流+浏览器全链+V4 smoke/rollback；FINAL-REPORT 45 项 |

## 提交计划（小步）

1. docs/preflight（本次）；2. photo red tests；3. photo contract；
4. photo UI；5. agent lineage red（已含）；6. agent lineage 实现；
7. usage UI/reconciliation；8. parallel red（已含）；9. parallel runtime；
10. workflow UI；11. UAT v2 driver；12. V4 shadow correction；
13. rate limit；14. browser/UI fixes；15. docs/gate/final report。

## 红线（重申）

不启动长训练；不动未跟踪资产；不 merge/push/deploy；不删历史记录；
修正追加式；`prod_v4_best_r1` 保持（加载恢复测试后必须恢复）；
不伪造人工真值/准确率/并行性能/审核结果/Usage 归属；
P1 不得改名 P2 关闭；脚本不得直写业务 SQLite；测试不碰运行中真实服务。

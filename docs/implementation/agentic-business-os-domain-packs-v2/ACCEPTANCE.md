# ACCEPTANCE · Domain Packs V2

> 三类验收：机器（测试/对账）、浏览器（四视口截图+DOM/API 对账）、人工（用户）。
> `partial` 不得过 Gate。

## Gate G0 · 现场冻结

- [x] 必读文档完成（EXECUTION-LOG）
- [x] 安全基线记录（HEAD `d00953ad` / branch / worktree / 服务 4 UP / DB ok / 无训练 / production 未切）
- [x] 治理文档六份建立
- [x] 每个 P0/P1 有红测试复现（先红后绿，见 EXECUTION-LOG）

## Gate G1 · Phase A（已通过，2026-08-11）

- [x] 四视口（1440×900 / 1280×800 / 1024×768 / 768×1024）浏览器截图+DOM 断言（8 张截图；iframe 精确断点法，方法已在报告披露）
- [x] current projection API/DB 对账（旧 250 不在 current 计数：current=2，superseded=254）
- [x] 快速目标刷新恢复（浏览器复验 abosv2_goal_refresh_1440.png）
- [x] 识别详情数据真实（abosv2_task_detail_1440.png）
- [x] Service Tier 诚实化（abosv2_tier_honest_1440.png）
- [x] supersession 单测/集成测试（7+ 项红转绿；全量 1191 passed）
- [x] 附加回归修复：ABOSV2-P1-008 topbar 隐藏

## Gate G2 · Phase B（已通过，2026-08-11）

- [x] 一条识别全链 ID 对账报告（EXECUTION-LOG：goal/run/work/corr/task/trace/evidence/usage；sku_count=4）
- [x] 投影重建 hash/count 一致（reconcile consistent=true，hash e80ea04d…，outbox 全 dispatched）
- [x] 失败恢复演示（run-637bcd55272842c5 failed → retry 同一 run succeeded）
- [x] 红测试先红后绿（test_abos_v2_control_plane.py 7 项）；全量 1201 passed

## Gate G3–G9（未开始）

- 见 IMPLEMENTATION-LIST 对应行。

## 人工验收记录

（等待用户验收；机器/浏览器验收通过前不预约人工验收。）

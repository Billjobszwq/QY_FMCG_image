# ACCEPTANCE · Domain Packs V2

> 三类验收：机器（测试/对账）、浏览器（四视口截图+DOM/API 对账）、人工（用户）。
> `partial` 不得过 Gate。

## Gate G0 · 现场冻结

- [x] 必读文档完成（EXECUTION-LOG）
- [x] 安全基线记录（HEAD `d00953ad` / branch / worktree / 服务 4 UP / DB ok / 无训练 / production 未切）
- [x] 治理文档六份建立
- [ ] 每个 P0/P1 有红测试复现

## Gate G1 · Phase A（未开始）

- [ ] 四视口（1440×900 / 1280×800 / 1024×768 / 768×1024）浏览器截图+DOM 断言
- [ ] current projection API/DB 对账（旧 250 不在 current 计数）
- [ ] 快速目标刷新恢复
- [ ] 识别详情数据真实
- [ ] Service Tier 诚实化
- [ ] supersession 单测/集成测试

## Gate G2 · Phase B（未开始）

- [ ] 一条识别全链 ID 对账报告
- [ ] 投影重建 hash/count 一致
- [ ] 失败恢复演示

## Gate G3–G9（未开始）

- 见 IMPLEMENTATION-LIST 对应行。

## 人工验收记录

（等待用户验收；机器/浏览器验收通过前不预约人工验收。）

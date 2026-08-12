# STATUS

更新时间：2026-08-12（V3 实施收口）。

## 唯一 Gate

`READY_FOR_REAL_DATA_UAT`

含义：T0–T12 全部 VERIFIED_LOCAL、G0–G8 通过、P0/P1 清零、UAT 机器预演
（05 文档七段）23/23 通过。等待用户以真实客户/地址/问卷做最终 UAT。
**不等于** ACCEPTED / COMPLETE / PRODUCTION_READY。

## 实施状态（T0–T12 全部 VERIFIED_LOCAL）

| Task | 状态 | 关键证据 |
|---|---|---|
| T0 审计 | VERIFIED_LOCAL | HEAD 47c01c43 基线；备份 platform_pre_v3_20260812_030918.sqlite（integrity ok）；READING-LIST.md |
| T1 统一控制面 | VERIFIED_LOCAL | P0-001..004 + P1-015 红测试 8 项绿（a94cdc82）；reconcile 含业务事实对账 |
| T2 首页总控 | VERIFIED_LOCAL | dashboard 八段 API+UI；日历/便签服务端持久化；主管可调宽/底部/全屏（90eaa7e9/d9923cb5） |
| T3 Import Center | VERIFIED_LOCAL | 14 模板 round-trip；坏 fixture 逐行错误→修复→幂等提交（419043d6） |
| T4 Agent Runtime | VERIFIED_LOCAL | 7 Agent 定义+有界 health；工具循环 8 意图；invoke 落 run/event/usage（e2de6a7d） |
| T5 工作流画布 | VERIFIED_LOCAL | React Flow 默认；wait 持久化 timer 重启恢复；join all/any/quorum（e7b3361c） |
| T6 问卷 Builder | VERIFIED_LOCAL | 空白→发布→矩阵响应→计分；matrix/description 题型（37a45c53） |
| T7 位置外勤 | VERIFIED_LOCAL | geocode SPI 诚实降级；手工坐标；路线调版 v2；maplibre 降级散点（5c634489） |
| T8 V4 best 切换 | VERIFIED_LOCAL | shadow→switch→rollback→switch；8091 加载 prod_v4_best_r1 真实识别 sku=6（1fd048b8） |
| T9 BI 工作台 | VERIFIED_LOCAL | 受限公式 DSL fail-closed；下钻；看板 CRUD（d64a436a） |
| T10 Usage 工作台 | VERIFIED_LOCAL | 汇总/趋势/下钻/预算/CSV；跨客户 403（bbeaa643） |
| T11 帮助/管理拆分 | VERIFIED_LOCAL | help 模块全员；系统管理仅管理员导航过滤（7fd64b66） |
| T12 UAT 预演收口 | VERIFIED_LOCAL | 预演 23/23（v3_uat_rehearsal_report.json）；restart 四服务 UP；安全快检通过 |

## 本轮现场事实

- HEAD：见 `git log`（本轮 commit 链 a94cdc82…T12 收口）；分支
  `feat/nextgen-training-cycle-v2`；未 merge/push/deploy。
- 迁移：041–046 已应用（现场核验）；SQLite integrity ok；备份在
  `.platform/backups/`。
- production bundle：`prod_v4_best_r1`（用户授权的本机受控切换，
  回滚已验证，CURRENT.previous.json 备份在位）。
- 服务：8091/8092/8300/8400 全部 UP（abos restart 验证）。
- 测试：hermetic 1328 passed；host_mps 6 passed；typecheck/build 通过。

## 诚实残留与外部阻断（不阻断 UAT）

- 地理编码 Provider 与地图瓦片未配置 Key：模块 degraded，配置指引
  内置（GEOCODER_PROVIDER/AMAP_API_KEY/TENCENT_MAP_KEY/MAP_TILES_URL）；
  手工/导入坐标路径可用。
- 本轮未启动长时间训练（红线）；训练 dry-run 对不可训练快照
  fail-closed（gold_region_v1=0，需人工金标后才可训练）。
- Supervisor LLM 合成未配置 DEEPSEEK_API_KEY 时为规则工具循环
  （诚实标注 provider，不影响工具执行）。
- 浏览器四视口验收部分经 CSS zoom/iframe 仿真（自动化窗口物理尺寸
  受限，方法与 V2 一致并已披露）。

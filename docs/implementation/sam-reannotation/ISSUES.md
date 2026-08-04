# SAM 辅助重标注专项 · 问题登记

格式：ID | 问题 | 严重性 | 证据 | 状态 | 修复 commit。

| ID | 问题 | 严重性 | 状态 |
|---|---|---|---|
| SAM-001 | 手册必读清单第一项 `AGENTS.md` 在仓库中不存在 | 低 | 已用 `ls`/搜索确认无此文件；项目实际工作流约定在 `docs/CODEX-PROJECT-HANDBOOK.md` 与 superpowers plans 中，已读 | 已记录（不阻断） |
| SAM-002 | Label Studio 容器无法在本机启动：docker pull `humansignal/label-studio:latest` 被 registry 拒绝，本地无镜像 | 中（阻断人工双审界面） | 集成代码已用 FakeClient 契约测试；驱动离线落盘 `ls_payload.json` 待 LS 恢复后导入；人工环节状态 awaiting_human_review | 待用户网络/镜像源解决 |
| SAM-003 | 货架检测器 sku_v4_best 对照片1106/1107/百事&可口（单品近拍、未注册 SKU）conf=0.1 仍几乎无输出 | 低 | benchmark 点源改用确定性网格（benchmark_grid_v1，仅性能测量）；此类照片恰属 completeness queue 需人工/SAM automatic 发现的对象 | 已记录（设计内） |
| SAM-004 | 硬约束通过率偏低（field 点 6.5%）：触碰粗 ROI 边界/多连通域→降级人工 | 中 | 保守设计预期（手册§六.6）；阈值校准须用独立校准集（禁用 diagnostic_v1）；S1 以人工框终判 | 待校准集 |

（暂无其他问题。执行中发现问题按上述格式追加。）

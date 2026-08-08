# 05 Web 工作台与 API 契约

## Web（现有 Shell 内，不新建系统）
右侧跨页面黄色"主管笔记"抽屉：对话区/今日待办/Running/Waiting-Blocked/Needs Review/
Resolved/命令预览与批准/证据引用/资源状态/当前 Graph/Agent 健康。
任务板：Todo → Running → Waiting → Review → Done（用户验收或自动验收契约才 Done）。
借鉴 dashi-taskboard：UI/CLI/Agent 共用 API、乐观版本、实时事件、任务关联 thread/run；
不复制无认证模式/CDP 注入/绕过正式 API。
保留并改造真实可操作：Overview/Recognition/Annotation/Assets/Training/Cascade/
Model Runtime/New Packaging/Status/Graph Runs。

## Recognition Profile（五入口同一契约）
production_legacy / nextgen_detector / nextgen_detector_segmenter /
nextgen_detector_classifier / nextgen_full_cascade / shadow_compare。
未训练：可展示、disabled、显示 blocker、禁退化为任意路径。
结果保存：profile/version/各 artifact/policy/confidence/abstain/evidence/latency/
resource usage/billable units。Web/API/Agent 调同一 Domain Service。

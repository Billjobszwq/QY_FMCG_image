# Project Logic Chain V3 · ACCEPTANCE

## 机器侧验收（本轮必须完成）
见任务书 §十七 15 项与 §十八 22 项测试矩阵（映射见实施计划 §3）。
完成后状态必须为 **AWAITING_HUMAN_ACCEPTANCE**，输出 10 条真实访问链接。

## 人工侧验收（Agent 不得代办）
- 5 assisted + 5 blind + ≥2 同图对照的真实画框与 SKU 结论；
- 双审、分歧、仲裁由不同真人完成；
- Agent 不得为通过验收自创 human_final。

## 验收检查清单（5+5 批）
1. 正确导入（rq_v2 校验通过）  2. 原图显示  3. assisted 自动框/SKU 可见
4. blind 无任何 prediction  5. 多区域增删改  6. SKU/unknown/new_packaging
7. 登录认领  8. 一审/二审/分歧/仲裁功能  9. 原子提交（部分失败零落账）
10. gold_region 进度  11. truebox 导出  12. evaluator 可读  13. 浏览器控制台无错误
14. 刷新后数据保持  15. API/页面/DB 数量一致

## 旧项目与旧制品零覆盖声明（验收时填写）
- Label Studio 项目 10~13：未删除/未覆盖（证据：项目列表快照）
- review_queue_diag_v1.json：未修改（证据：文件 SHA 前后一致）
- diagnostic_v1.json：未修改（0444 只读）

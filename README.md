# QY_FMCG_image

货架陈列 SKU 检测/识别平台：YOLO 画框 + 级联分类器 + Label Studio 标注审核闭环。

- 后端 / 训练 / 级联链路：见 `src/` 与 `docs/`，设计文档见
  `2026-07-31-general-sku-recognition-system.md`
- 前端（PostHog 风格桌面式窗口框架）：见 [`frontend/README.md`](frontend/README.md)
  （运行：`cd frontend && npm install && npm run dev`）
- Label Studio 基础设施：`compose.yaml` + `configs/label-studio/`

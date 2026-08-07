# NextGen V2 · ISSUES

## N2-ISSUE-001 交付报告计数纠偏
- 状态：CLOSED（Task 0）。上一报告默认 1010 passed 在本机成立，但 Codex 受限环境
  fresh 为 1002/8 failed；根因为测试宿主 MPS 耦合。已 hermetic 化并留 host suite。

## N2-ISSUE-002 未跟踪证据分类
- 状态：OPEN（Task 0）。reports/backfill_visible_sku/*.json（3 个）与
  reports/gltc_web_qa_training_console.png 为历史证据，保留不删除，随 docs commit 分类归档。

## N2-ISSUE-003 V1 控制链缺口（承接 01 审计 §6）
- NextGen API 写链不全、dataset build 固定空 rows、Graph 内存态、Web 只读卡、
  识别页无 profile。由 Task 1/2/7/10/11 关闭。

## N2-ISSUE-004 批1/批2 原图不可达（阻断批1/2 像素级链路）
- 状态：OPEN（WAITING_FOR_USER_DATA_ACCESS）。
- 事实：`.training_data/manifest.json` / `.eval/batch2/manifest.json` 只有
  sha256/width/height，无本地 blob；url（sys-new.spar-china.com）实测返回
  HTML 登录页（2KB，非图像），原图无法下载。批3 完整可用
  （`.batch3_clean/blobs` 22,659 图 + 571,404 坐标）。
- 影响：批1/2 的 6,512 张照片无法进入质量分析/SAM/像素级训练；
  其 258,708 个坐标保留为 legacy_coordinate_verified（身份/映射已对账），
  待用户提供批1/2 原图（内网访问或本地目录）后幂等并入。
- 处置：本轮以批3（22,659 图/571,404 点）为主执行严格过滤/SAM/快照/训练
  闭环；批1/2 缺口不静默吞掉，最终报告如实标注。

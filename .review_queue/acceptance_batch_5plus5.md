# 5+5 真实验收批（AWAITING_HUMAN_ACCEPTANCE）

- 生成时间（UTC）：2026-08-07T14:20:36.788354+00:00
- git commit：`d89fc822beab0cd172a97e1ff441e50ebd5c7634`
- 来源队列：`.review_queue/review_queue_diag_v2.json`（queue_version=rq_v2，250 项）
- 状态：**AWAITING_HUMAN_ACCEPTANCE** —— 机器侧 15 项自检已完成，等待真人审核

## 一、10 条验收任务访问链接

| # | LS 访问链接 | photo_id | sha256(前16) | 验收模式 | 队列模式 | 同图对照 | 平台 task_id | claim_token |
|---|---|---|---|---|---|---|---|---|
| 1 | [http://127.0.0.1:8300/projects/19/data/127](http://127.0.0.1:8300/projects/19/data/127) | 35996301 | bda01a44f53b8405… | assisted | double_review | 35996301 | `rt_doubl_35996301_bda01a44f53b8405` | `aeA-p8PjuFRTpXzQ` |
| 2 | [http://127.0.0.1:8300/projects/20/data/324](http://127.0.0.1:8300/projects/20/data/324) | 35996301 | bda01a44f53b8405… | blind | blind_manual | 35996301 | `rt_blind_35996301_bda01a44f53b8405` | `yGB_yrzzTGO7G_M9` |
| 3 | [http://127.0.0.1:8300/projects/19/data/129](http://127.0.0.1:8300/projects/19/data/129) | 36013437 | b8af6590f7c4cfd6… | assisted | double_review | 36013437 | `rt_doubl_36013437_b8af6590f7c4cfd6` | `-4xGmcJ2rDyYvtDm` |
| 4 | [http://127.0.0.1:8300/projects/20/data/325](http://127.0.0.1:8300/projects/20/data/325) | 36013437 | b8af6590f7c4cfd6… | blind | blind_manual | 36013437 | `rt_blind_36013437_b8af6590f7c4cfd6` | `HeZq3sw1ZzR7DLXn` |
| 5 | [http://127.0.0.1:8300/projects/19/data/124](http://127.0.0.1:8300/projects/19/data/124) | 35980695 | 8b7f62975a4db6d8… | assisted | double_review | - | `rt_doubl_35980695_8b7f62975a4db6d8` | `584HS_VZJ4DQL3BW` |
| 6 | [http://127.0.0.1:8300/projects/19/data/125](http://127.0.0.1:8300/projects/19/data/125) | 35984084 | 312996e4d842e528… | assisted | double_review | - | `rt_doubl_35984084_312996e4d842e528` | `TiuGcYTbxgQXqSLL` |
| 7 | [http://127.0.0.1:8300/projects/19/data/126](http://127.0.0.1:8300/projects/19/data/126) | 35995935 | 65ee62d4c7cac121… | assisted | double_review | - | `rt_doubl_35995935_65ee62d4c7cac121` | `UgSTXSkJlw6kbXec` |
| 8 | [http://127.0.0.1:8300/projects/20/data/348](http://127.0.0.1:8300/projects/20/data/348) | 36177757 | 07c36a919cee0b7b… | blind | blind_manual | - | `rt_blind_36177757_07c36a919cee0b7b` | `PgQ9I01ZduV2C2tK` |
| 9 | [http://127.0.0.1:8300/projects/20/data/349](http://127.0.0.1:8300/projects/20/data/349) | 36177761 | 307df41c1fa60b9b… | blind | blind_manual | - | `rt_blind_36177761_307df41c1fa60b9b` | `QReCQORbA9ryB2dq` |
| 10 | [http://127.0.0.1:8300/projects/20/data/350](http://127.0.0.1:8300/projects/20/data/350) | 36193949 | 3c7642f062ce3ce0… | blind | blind_manual | - | `rt_blind_36193949_3c7642f062ce3ce0` | `gP84U_FiHm4BUrU5` |

LS 项目入口：[http://127.0.0.1:8300/projects/19（assisted 双审）](http://127.0.0.1:8300/projects/19) ·
[http://127.0.0.1:8300/projects/20（blind 盲审）](http://127.0.0.1:8300/projects/20)

## 二、模式说明

- **assisted（double_review，5 任务）**：辅助双审。两名**不同**审核员各自独立
  画框并给出 SKU 结论；两次提交一致（区域级 one-to-one IoU≥0.75 且 SKU 结论
  相同）→ human_final；分歧 → 升级仲裁（第三名审核员一锤定音 → gold_verified）。
  注：本批构建时无可用模型提案，自动框栏位为空（fail-closed，未伪造 prediction）。
- **blind（blind_manual，5 任务）**：盲审。零模型信息（界面不出现任何模型输出），
  审核员凭肉眼画框并给 SKU 结论；同样需二次审核。
- **同图对照（4 任务 = 2 张照片 × 2 模式）**：同一照片既走 assisted 又走
  blind（照片 35996301、36013437），用于对照辅助/盲审结论的一致性。
  两条链路任务相互独立（gold 按 task_id 分组，互不污染）。

## 三、操作指引（真人）

1. 打开任务链接（或凭 claim_token 从平台认领链接进入）。
2. 双审：请两位不同审核员分别独立完成同一任务；分歧时由第三人仲裁。
3. 盲审：不得参考任何模型输出；独立完成画框与 SKU 结论。
4. 区域可多区域增删改；SKU 无法识别时选 unknown，新包装选 new_packaging。
5. 提交后刷新页面确认数据保持；如需复验数量：WorkItems API 与审核进度同库一致。

## 四、声明（重要）

> **真实框与 SKU 结论必须由人提交。** Agent 仅准备了本验收批的机器侧材料
> （链接、token、一致性证据、15 项自检），未提交、也绝不提交任何
> human_final / gold_verified / 真实框 / SKU 结论。双审、分歧、仲裁必须由
> 不同真人完成。

机器侧自检明细与全部证据见同目录 `acceptance_batch_5plus5.json`。

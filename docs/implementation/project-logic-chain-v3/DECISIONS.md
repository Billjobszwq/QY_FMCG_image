# Project Logic Chain V3 · DECISIONS

## D1 canonical 映射源 = clean_manifest.json（按 photo_id 查询）
- 背景：diagnostic_v1.json 不可变（0444 只读冻结协议），其 zip 配对不可信（2/500）。
- 决定：新增 src/data/photo_identity.py，一律按 photo_id 从 .batch3_clean/clean_manifest.json
  查 sha256；队列/导入/评估禁止位置 zip。manifest 缺失条目 → fail-closed。
- 否決替代：重写 diagnostic_v1.json（违反不可变协议）。

## D2 rq_v1 失效方式 = 追加式账本，不改任务行
- review_task_v1 有 no_update/no_delete 触发器；采用 review_queue_ledger_v1 +
  review_task_invalidation_v1 追加记录；活动查询按 active queue version 过滤。

## D3 V2 队列保持原实验设计
- 前 200 ID double、seed=20260804 盲抽 50、24 张同图对照、250 任务/226 唯一照片；
  仅修正 SHA 来源（按 ID 查询）。理由：实验设计本身无缺陷，错的只是配对。

## D4 审核状态唯一事实源 = DB 事件推导
- JSON 队列降级为不可变导入制品；所有页面/门禁走统一查询服务 review_state。

## D5 migration 020 给 gold_region_v1 追加列而非重建表
- 追加 image_width/image_height/coord_version（旧行默认值）；保持不可变触发器不动。

## D6 双审一致性 = one-to-one IoU 匹配 + canonical sku_id
- IoU 阈值版本化写入审核协议与证据；不要求人工坐标完全相等；region_id 相同不构成一致。

## D7 仲裁粒度 = conflict group / region pair
- 未分歧区域不受仲裁影响；逐区域 gold_verified；原提交保留 superseded。

## D8 验收策略 = 5+5 小规模批先行，状态 AWAITING_HUMAN_ACCEPTANCE
- 机器不自创 human_final；真实框与 SKU 结论必须由人提交。

# Project Logic Chain V3 · SOURCE-OF-TRUTH

> 初版（文档基线）。每实体：权威文件/表、派生缓存、禁止作为事实源的旧文件、
> 写入者、读取者、版本规则、不可变规则、失效/替代规则。实施中逐项补全。

| 实体 | 权威源 | 派生缓存 | 禁作事实源 | 写入者 | 读取者 | 版本/不可变/失效规则 |
|---|---|---|---|---|---|---|
| Asset | source_asset_inventory_v1（platform.sqlite） | — | 各临时下载目录清单 | 登记脚本 | 全链 | 追加式；触发器禁删改 |
| Source URI | 同上（source_uri 列） | — | — | 同上 | 同上 | 同上 |
| Photo/SHA identity | .batch3_clean/clean_manifest.json（photo_id→sha256）★本轮锁定 | blobs/{sha前2}/{sha} | diagnostic_v1.json 的位置 zip 配对 | 冻结脚本（只读） | 队列/导入/评估 | 只读；错配经账本失效 |
| SKU | data/sku_registry.json（canonical sku_id） | KB vectors | 展示名字符串 | Registry 维护 | 评估/审核 | 版本化；别名映射 |
| Package version | package_decision + Registry | — | — | 人工/VLM 流 | 评估 | 终结行不可变；supersede 追加 |
| Annotation task | review_task_v1 | 队列 JSON（导入制品） | 静态 JSON 的 status 字段 | 导入脚本 | 8400 API/LS | 不可变；失效走账本 |
| Review event | review_event_v1 | — | — | 审核 API | 状态推导 | 追加式不可变 |
| Gold region | gold_region_v1 | truebox 导出 | prediction/submitted/conflict | 人工提交（唯一） | 导出/评估 | 不可变；仲裁 supersede 留痕 |
| Protocol set | .data_protocol/*.json | — | — | freeze 脚本 | 守卫/评估 | 只读 0444；只追加新版本 |
| Dataset snapshot | dataset_snapshot 表 | .datasets/ | 旧 sku_v6/crop_dataset | builder | 训练门禁 | registered/rejected/superseded |
| Training run | training_run 表 | runs/ 目录 | — | 门禁授权 | 监控 | 状态机；不覆盖 run |
| Model/bundle | catalog bundle manifest | — | 旧 v6 权重 | 发布流程（需授权） | 8091 | 原子切换；本轮冻结 |
| Graph run | graph_run/node_execution | — | — | Graph kernel | 工作台 | checkpoint 可重放 |
| Recognition result | recognition_task | — | — | 8091/级联 | 工作台 | 幂等键 |
| Usage/billing | usage_event + cascade_usage | — | — | 各能力点 | 报表 | 重算走 correction |
| Human feedback | review_event_v1 + gold_region_v1 | — | 模型 suggestion | 真人（session actor） | 真值链 | prediction 永不进入 |

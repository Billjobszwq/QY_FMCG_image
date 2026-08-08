# 02 SKU 长尾数据政策（sku_data_readiness_policy_v1）

统计维度（每类）：raw crops / unique source photos / unique SHA / unique near-dup groups /
unique stores / unique sessions / package versions / scene / quality / target-size /
occlusion-reflection diversity / Registry 状态 / LS taxonomy 状态。

**以有效独立组（leakage group）数量为主依据**分层：
- Tier A Mature：独立组 ≥300 且覆盖达标 → 闭集分类 + 上限/平方根采样 + hard negative 挖掘；
- Tier B Growing：100–299 → 适度过采样+增强+混淆矩阵补 hard negative；
- Tier C Tail：30–99 → metric/prototype/retrieval 优先，禁高置信自动接受；
- Tier D Prototype：<30 或身份未裁决 → 新包装/未知工作流，few-shot prototype，
  禁重复增强伪造规模，需业务决定。

输出：83 类完整统计、Tier 分布、每类有效样本、建议（加强/保留/专家头/合并/舍弃）、
头尾差距、最差十类、混淆商品族、采集优先级。
不可变产物：reports/nextgen_v2/sku_data_readiness_policy_v1.json。

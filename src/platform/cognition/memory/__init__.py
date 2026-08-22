"""memory 子包：规范三层记忆 L1/L2/L3 生命周期与旧表只读适配。

写权限矩阵（04 §3）：
- L1：所有角色可 append-only；
- L2：仅 Consolidator 可生成 candidate；发布必须人类批准；
- L3：仅 Consolidator/Rules 可提 candidate；发布必须人类批准，
  且反例未清、最小独立事件数不足时不得发布。
普通 Domain Agent 不得直接写 L2/L3。
"""

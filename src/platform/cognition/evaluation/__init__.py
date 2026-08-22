"""cognition evaluation 子包（Task 12）：固定金标准 + 分层指标 + 负例账本。

分层指标（05 §九）：retrieval / citations / safety；禁止单一总分。
所有指标函数为纯函数（确定性、可复现），由 report.py 组装并哈希。
"""

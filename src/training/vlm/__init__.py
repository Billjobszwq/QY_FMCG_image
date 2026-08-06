"""VLM-008：Qwen3-VL FMCG 数据链路（Canonical Sample / builder / 防泄漏 / HF 格式）。

红线：JSONL 只是不可变审计清单；MLX-VLM 训练制品必须是 HF Dataset 的
images + messages；禁止手工 <|vision_start|>；禁止随机 9:1 划分。
"""

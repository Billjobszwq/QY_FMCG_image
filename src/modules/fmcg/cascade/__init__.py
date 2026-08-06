"""FMCG Vision Cascade Domain Pack（方案 B：Qwen3-VL 4B + Graph+Loop 级联）。

模块边界（L0 总纲 §6）：
- Graph+Loop v2（src/platform/kernel/loop.py）是唯一 Orchestrator；
- 本模块经 Manifest + CapabilityRegistry 向平台注册能力，
  平台内核不得反向 import 本模块；
- 不建设第二套数据库/任务/审核/计费系统。
"""

CASCADE_MODULE_VERSION = "1.0.0"

"""FMCG 级联适配器包（VLM Task 6/7 将在此实现具体 adapter）。

本包只做能力 ID 与 adapter 实例的挂载点；真实适配器由组合根
（src/composition/build.py）注入，platform 不得反向 import 本包。
"""

from __future__ import annotations

ADAPTERS_PACKAGE_VERSION = "0.1.0"


class CapabilityAdapterError(Exception):
    """受控 capability 错误：legacy/后端异常统一映射为此类型。

    Graph 层据此决定回落或转人工，不得吞掉异常后伪造成功。"""

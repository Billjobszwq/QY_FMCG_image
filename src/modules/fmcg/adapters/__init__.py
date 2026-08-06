"""FMCG 级联适配器包（VLM Task 6/7 将在此实现具体 adapter）。

本包只做能力 ID 与 adapter 实例的挂载点；真实适配器由组合根
（src/composition/build.py）注入，platform 不得反向 import 本包。
"""

from __future__ import annotations

ADAPTERS_PACKAGE_VERSION = "0.1.0"

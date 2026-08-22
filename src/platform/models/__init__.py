"""统一模型管理（系统级模块）。

边界（DEC-M001/M002）：本包只负责 Connection/Catalog/Binding 的受控
配置、Secret 保管、Endpoint 安全、Provider 适配与 scope-first 解析；
实际执行继续进入既有 Cognition/Agent Runtime/Vision/Usage/Evidence 链路，
不建立平行运行内核。
"""

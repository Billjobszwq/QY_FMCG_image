"""Platform V2 存储层（W5）：SQLite 开发适配器 + 不可变 migrations。

红线：
- 只暴露类型化方法，不对外提供任意 SQL 执行能力；
- migration 只追加不修改（sha256 防篡改校验）；
- 时间戳一律 UTC ISO-8601。
"""

from .store import PlatformStore, StoreError

__all__ = ["PlatformStore", "StoreError"]

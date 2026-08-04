"""组合根：连接平台（src/platform）与 Domain Packs（src/modules）。

依赖方向：src/modules → src/platform（允许）；src/platform → src/modules（禁止，AST 守卫）。
本包是唯一同时 import 两者的位置。
"""

from .build import build_app_with_bundle, build_production_bundle

__all__ = ["build_production_bundle", "build_app_with_bundle"]

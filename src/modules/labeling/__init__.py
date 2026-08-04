"""labeling 域模块：Label Studio 闭环（M4）。"""

from .service import LabelingError, LabelingService

MODULE_ID = "labeling"
__all__ = ["LabelingError", "LabelingService", "MODULE_ID"]

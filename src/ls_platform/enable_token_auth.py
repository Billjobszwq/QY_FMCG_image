"""启用 Label Studio 组织的 legacy API token 认证。

LS 1.23 默认禁用旧版 token（影响 API 与 ML 后端访问）。本脚本通过 Django ORM
将当前组织的 org.jwt.legacy_api_tokens_enabled 置为 True。
用法：python -m src.ls_platform.enable_token_auth"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ..common.config import PROJECT_ROOT

# label_studio 的 settings 用 `from core.settings.base import *`，需把包目录加入 sys.path
import label_studio as _ls

LS_PKG = str(Path(_ls.__file__).parent)
if LS_PKG not in sys.path:
    sys.path.insert(0, LS_PKG)

os.environ["LABEL_STUDIO_BASE_DATA_DIR"] = str(PROJECT_ROOT / ".label-studio")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "label_studio.core.settings.label_studio")


def main():
    import django

    django.setup()
    from organizations.models import Organization  # LS 以包目录为 sys.path 根，app 名为 organizations

    updated = []
    for org in Organization.objects.all():
        jwt = getattr(org, "jwt", None)
        if jwt is not None:
            jwt.legacy_api_tokens_enabled = True
            jwt.save()
            updated.append((org.id, org.title))
            print(f"[enable_token_auth] 组织 {org.id} ({org.title}): legacy_api_tokens_enabled = True")
        else:
            print(f"[enable_token_auth] 组织 {org.id} 无 jwt 关联对象，跳过")
    if not updated:
        print("[enable_token_auth] 未找到组织，请确认 Label Studio 已初始化")
    return updated


if __name__ == "__main__":
    main()

import sys
import os
import pathlib

import pytest

# 让测试可直接 import src.* 而无需安装包
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# Hermetic 隔离：src/common/config.py 在导入时会把 .env 灌入 os.environ
# （含生产凭据 PLATFORM_ADMIN_CREDENTIALS）；测试必须自行通过
# monkeypatch 显式设定认证环境变量，不得继承宿主机值。
_AUTH_ENV_KEYS = ("PLATFORM_ADMIN_CREDENTIALS", "PLATFORM_ADMIN_PASSWORD",
                  "PLATFORM_USERS")


@pytest.fixture(autouse=True)
def _hermetic_auth_env():
    saved = {k: os.environ.pop(k, None) for k in _AUTH_ENV_KEYS}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v

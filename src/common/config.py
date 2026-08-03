"""集中配置：所有敏感项只走环境变量 / 本地 .env，禁止硬编码。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载器，避免额外依赖；仅 setdefault，不覆盖已有环境变量。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    omlx_base_url: str = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8455/v1")
    omlx_api_key: str = os.environ.get("OMLX_API_KEY", "")
    vlm_model: str = os.environ.get("OMLX_VLM_MODEL", "gemma-4-31b-it-4bit")
    embed_model: str = os.environ.get("OMLX_EMBED_MODEL", "Qwen3-Embedding-0.6B-8bit")
    ocr_box_model: str = os.environ.get("OMLX_OCR_BOX_MODEL", "PaddleOCR-VL-1.5-6bit")
    ocr_text_model: str = os.environ.get("OMLX_OCR_TEXT_MODEL", "DeepSeek-OCR-2-4bit")
    embed_dim: int = int(os.environ.get("OMLX_EMBED_DIM", "1024"))
    reference_dir: Path = Path(os.environ.get("KB_REFERENCE_DIR", str(PROJECT_ROOT / "搭建初期P1")))
    field_xlsx: Path = Path(os.environ.get("FIELD_XLSX", str(PROJECT_ROOT / "实景照片.xlsx")))
    data_dir: Path = Path(os.environ.get("KB_DATA_DIR", str(PROJECT_ROOT / ".kb")))
    oss_base: str = os.environ.get("OSS_BASE", "https://bucket-spar.oss-cn-shanghai.aliyuncs.com")
    oss_prefix: str = os.environ.get("OSS_PREFIX", "photo/")
    request_timeout: float = float(os.environ.get("OMLX_TIMEOUT", "180"))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

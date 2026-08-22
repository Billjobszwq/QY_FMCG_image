"""omlx（OpenAI 兼容）本地模型客户端：嵌入 / VLM 结构化抽取 / OCR。

所有调用走本地端点，图像不出网。带 thinking 的模型会把 token 预算耗在 reasoning 上，
故 _chat 在 content 为空时自动放大 max_tokens 重试一次。

统一模型管理 V1（M8/DEC-M010）：本模块是**迁移期兼容层**——
平台运行态（认知索引/Agent）已改经统一模型管理的受管连接与账本；
独立 CLI（pipeline/labeling/catalog）仍走本 legacy env 通道。
约束：兼容层不是第二配置真源；``provider_source()`` 显式暴露来源，
首次使用写一次性告警，便于观测与逐步停用。"""
from __future__ import annotations

import base64
import json
import re
import warnings
from functools import lru_cache
from typing import Any

from openai import OpenAI

from .config import get_settings

_LEGACY_WARNED = False


def provider_source() -> str:
    """显式配置来源标注（可观测的迁移期回退，不是受管连接）。"""
    return "legacy_env:OMLX_API_KEY"


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    global _LEGACY_WARNED
    s = get_settings()
    if not s.omlx_api_key:
        raise RuntimeError("OMLX_API_KEY 未设置（见 .env.example）")
    if not _LEGACY_WARNED:
        _LEGACY_WARNED = True
        warnings.warn(
            "omlx 客户端使用 legacy env 通道（%s）；平台运行态请改经"
            "统一模型管理受管连接（见 taas-unified-model-management-v1）"
            % provider_source(),
            stacklevel=2)
    return OpenAI(base_url=s.omlx_base_url, api_key=s.omlx_api_key, timeout=s.request_timeout)


def _data_uri(image_bytes: bytes, mime: str = "image/png") -> str:
    # 以魔数为准自动纠正 mime：实景多为 jpeg，即便调用方传 png 也能正确编码
    if image_bytes[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"


def embed(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    resp = _client().embeddings.create(model=s.embed_model, input=texts)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


def _strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _chat(image_bytes: bytes | None, prompt: str, model: str, max_tokens: int, mime: str) -> str:
    content: Any = prompt
    if image_bytes is not None:
        content = [
            {"type": "image_url", "image_url": {"url": _data_uri(image_bytes, mime)}},
            {"type": "text", "text": prompt},
        ]
    for mt in (max_tokens, max_tokens * 3):
        r = _client().chat.completions.create(
            model=model, messages=[{"role": "user", "content": content}], max_tokens=mt, temperature=0
        )
        text = (r.choices[0].message.content or "").strip()
        if text:
            return text
    return ""


def vlm_extract(image_bytes: bytes, schema_prompt: str, mime: str = "image/png") -> dict:
    s = get_settings()
    text = _strip_fences(_chat(image_bytes, schema_prompt, s.vlm_model, 512, mime))
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"VLM 未返回 JSON: {text[:200]}")
    return json.loads(m.group(0))


def vlm_classify(image_bytes: bytes, question: str, options: list[str], mime: str = "image/png") -> str:
    s = get_settings()
    prompt = f"{question}\n只能从以下选项中选一个，只输出选项本身，不要解释：{options}"
    return _chat(image_bytes, prompt, s.vlm_model, 64, mime).strip()


def ocr_text(image_bytes: bytes, mime: str = "image/png") -> str:
    s = get_settings()
    return _chat(image_bytes, "逐行输出图中所有可见文字，不要解释。", s.ocr_text_model, 512, mime)


_LOC = re.compile(r"<\|LOC_(\d+)\|>")


def ocr_boxes(image_bytes: bytes, mime: str = "image/png") -> list[dict]:
    """PaddleOCR-VL：返回 [{text, bbox:[x1,y1,x2,y2]}]，坐标为模型原始 LOC 值。"""
    s = get_settings()
    raw = _chat(image_bytes, "逐行输出图中所有文字，保留位置标记。", s.ocr_box_model, 1024, mime)
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        nums = _LOC.findall(line)
        text = _LOC.sub("", line).strip()
        if len(nums) >= 4 and text:
            out.append({"text": text, "bbox": [int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])]})
    return out

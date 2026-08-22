"""真实 vector provider adapters（R2-05）。

安全契约：
- endpoint/model/key 只来自受控配置（环境变量），key 绝不写入日志、
  artifact、identity、hash 或异常文本；
- hermetic 测试禁止联网/自动下载模型：适配器只在显式配置后可用；
- provider 缺失时返回 UnavailableVectorProvider（诚实 degraded），
  不得用伪向量顶替。
"""
from __future__ import annotations

import os
from typing import Any

from .vector import UnavailableVectorProvider

# 受控环境变量（唯一配置入口）
ENV_PROVIDER = "TAAS_EMBEDDING_PROVIDER"
ENV_BASE_URL = "TAAS_EMBEDDING_BASE_URL"
ENV_MODEL = "TAAS_EMBEDDING_MODEL"
ENV_API_KEY = "TAAS_EMBEDDING_API_KEY"
ENV_DIMENSION = "TAAS_EMBEDDING_DIMENSION"
ENV_MODEL_REVISION = "TAAS_EMBEDDING_MODEL_REVISION"
ENV_NORMALIZATION = "TAAS_EMBEDDING_NORMALIZATION"


class OpenAICompatibleVectorProvider:
    """OpenAI-compatible embeddings adapter。

    复用环境内 openai SDK；endpoint/model/key 只从构造参数（来自受控
    配置）读取。key 不出现在 repr/identity/异常文本中。
    """

    provider_id = "openai-compatible"

    def __init__(self, *, endpoint: str, model_name: str, api_key: str,
                 dimension: int, model_revision: str = "",
                 normalization_version: str = "v1",
                 timeout_seconds: float = 30.0,
                 batch_size: int = 64) -> None:
        self.endpoint = endpoint or ""
        self.model_name = model_name or ""
        self.model_revision = model_revision or ""
        self.dimension = int(dimension or 0)
        self.normalization_version = normalization_version or "v1"
        self._api_key = api_key or ""
        self._timeout = timeout_seconds
        self._batch_size = max(1, int(batch_size))
        self._client = None

    # ---------- 身份（不含凭据） ----------

    def identity(self) -> dict[str, Any]:
        return {"provider_id": self.provider_id,
                "model_name": self.model_name,
                "model_revision": self.model_revision,
                "dimension": self.dimension,
                "normalization_version": self.normalization_version,
                "endpoint": self.endpoint}

    def __repr__(self) -> str:  # 凭据卫生：key 不入 repr
        return (f"OpenAICompatibleVectorProvider(endpoint="
                f"{self.endpoint!r}, model={self.model_name!r},"
                f" revision={self.model_revision!r},"
                f" dimension={self.dimension}, key=***)")

    # ---------- 可用性 ----------

    def available(self) -> bool:
        if not (self.endpoint and self.model_name and self._api_key
                and self.dimension > 0):
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _ensure_client(self):
        if self._client is None:
            if not self.available():
                raise RuntimeError(
                    "openai-compatible embedding provider 未配置/不可用")
            import openai
            self._client = openai.OpenAI(base_url=self.endpoint,
                                         api_key=self._api_key,
                                         timeout=self._timeout)
        return self._client

    # ---------- 编码 ----------

    def _embed(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure_client()
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i:i + self._batch_size]
            resp = client.embeddings.create(model=self.model_name,
                                            input=batch)
            for item in resp.data:
                vec = list(item.embedding)
                if self.dimension and len(vec) != self.dimension:
                    raise RuntimeError(
                        f"embedding 维度不匹配: 配置 {self.dimension},"
                        f" 返回 {len(vec)}")
                out.append(vec)
        if len(out) != len(texts):
            raise RuntimeError("embedding 返回数量与输入不一致")
        return out

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(list(texts))

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed(list(texts))


def provider_from_env(environ: dict | None = None) -> Any:
    """受控配置 → provider 实例。未配置 → UnavailableVectorProvider。

    key 只从环境读取；本函数不打印/记录任何凭据。
    """
    env = environ if environ is not None else os.environ
    kind = (env.get(ENV_PROVIDER) or "").strip().lower()
    if kind in ("openai-compatible", "openai"):
        try:
            dim = int(env.get(ENV_DIMENSION) or 0)
        except ValueError:
            dim = 0
        return OpenAICompatibleVectorProvider(
            endpoint=(env.get(ENV_BASE_URL) or "").strip(),
            model_name=(env.get(ENV_MODEL) or "").strip(),
            api_key=(env.get(ENV_API_KEY) or "").strip(),
            dimension=dim,
            model_revision=(env.get(ENV_MODEL_REVISION) or "").strip(),
            normalization_version=(env.get(ENV_NORMALIZATION)
                                   or "v1").strip())
    return UnavailableVectorProvider()

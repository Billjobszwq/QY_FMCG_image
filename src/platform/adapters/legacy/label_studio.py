"""legacy.label_studio adapter：代理 Label Studio 8300 REST API（M4）。

原则：
- 平台只把 LS 当作外部能力（Capability），不做 LS 内部假设；
- token 解析顺序：显式参数 > 环境变量 LABEL_STUDIO_API_KEY；无 token 仅健康只读；
- 所有网络/HTTP 错误归类为 LabelStudioAdapterError(kind)，绝不泄漏栈。
"""

from __future__ import annotations

import os
from typing import Iterable

import httpx

CAPABILITY_ID = "legacy.label_studio"


class LabelStudioAdapterError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class LabelStudioAdapter:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8300",
        api_token: str | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.environ.get("LABEL_STUDIO_API_KEY") or None
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    @property
    def capability_id(self) -> str:
        return CAPABILITY_ID

    # ---------- infra ----------

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def _headers(self, require_token: bool = True) -> dict[str, str]:
        if self.api_token:
            return {"Authorization": f"Token {self.api_token}"}
        if require_token:
            raise LabelStudioAdapterError("no_token", "未配置 LABEL_STUDIO_API_KEY")
        return {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | list | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        params: dict | None = None,
        require_token: bool = True,
    ) -> dict | list:
        try:
            resp = self._get_client().request(
                method,
                self.base_url + path,
                json=json,
                files=files,
                params=params,
                headers=self._headers(require_token),
                timeout=self.timeout,
            )
        except httpx.TimeoutException as e:
            raise LabelStudioAdapterError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise LabelStudioAdapterError("unreachable", str(e)) from e
        if resp.status_code == 401 or resp.status_code == 403:
            raise LabelStudioAdapterError("auth", f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise LabelStudioAdapterError("bad_response", f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except Exception as e:
            raise LabelStudioAdapterError("bad_response", "invalid JSON") from e

    # ---------- health / version ----------

    def health(self) -> dict:
        """不需要 token。返回 {"status": "healthy"/"unavailable", "detail": ...}"""
        try:
            resp = self._get_client().get(self.base_url + "/api/health/", timeout=self.timeout)
            if resp.status_code >= 400:
                return {"status": "unavailable", "detail": f"HTTP {resp.status_code}"}
            return {"status": "healthy", "detail": None}
        except httpx.HTTPError as e:
            return {"status": "unavailable", "detail": str(e)}

    def version(self) -> dict:
        return self._request("GET", "/api/version/", require_token=False)  # type: ignore[return-value]

    # ---------- projects ----------

    def list_projects(self) -> list[dict]:
        out = self._request("GET", "/api/projects/", params={"page_size": 100})
        return out["results"]  # type: ignore[index]

    def create_project(self, title: str, label_config: str, description: str = "") -> dict:
        return self._request(  # type: ignore[return-value]
            "POST",
            "/api/projects/",
            json={"title": title, "label_config": label_config, "description": description},
        )

    def get_project(self, project_id: int) -> dict:
        return self._request("GET", f"/api/projects/{project_id}/")  # type: ignore[return-value]

    def update_project(self, project_id: int, **fields) -> dict:
        return self._request("PATCH", f"/api/projects/{project_id}/", json=fields)  # type: ignore[return-value]

    def delete_project(self, project_id: int) -> None:
        self._request("DELETE", f"/api/projects/{project_id}/")

    # ---------- tasks ----------

    def import_tasks(self, project_id: int, tasks: list[dict]) -> dict:
        """以 JSON 任务列表导入（data.image 需为可访问 URL）。"""
        return self._request("POST", f"/api/projects/{project_id}/import", json=tasks)  # type: ignore[return-value]

    def import_files(self, project_id: int, files: Iterable[tuple[str, bytes]]) -> dict:
        """逐文件 multipart 导入（LS 1.23 单次 import 只收一个文件 part，实测确认）。

        LS 自行托管文件，避免本地路径依赖；返回汇总 task_count。"""
        total = 0
        for name, data in files:
            resp = self._request(
                "POST",
                f"/api/projects/{project_id}/import",
                files=[("file", (name, data, "image/jpeg"))],
            )
            total += int(resp.get("task_count", 0))  # type: ignore[union-attr]
        return {"task_count": total}

    def list_tasks(self, project_id: int, page_size: int = 100) -> list[dict]:
        out = self._request(
            "GET", f"/api/projects/{project_id}/tasks", params={"page_size": page_size}
        )
        return out if isinstance(out, list) else out["results"]  # type: ignore[index]

    def get_task(self, task_id: int) -> dict:
        return self._request("GET", f"/api/tasks/{task_id}/")  # type: ignore[return-value]

    # ---------- predictions / annotations ----------

    def create_prediction(
        self, task_id: int, result: list[dict], *, score: float, model_version: str
    ) -> dict:
        # LS 1.23：POST /api/predictions/（task 在 body）；嵌套端点
        # /api/tasks/{id}/predictions/ 仅支持 GET，POST 返回 404（实测确认）。
        return self._request(  # type: ignore[return-value]
            "POST",
            "/api/predictions/",
            json={"task": task_id, "result": result, "score": score,
                  "model_version": model_version},
        )

    def list_annotations(self, task_id: int) -> list[dict]:
        return self._request("GET", f"/api/tasks/{task_id}/annotations/")  # type: ignore[list-item]

    def export_annotations(self, project_id: int) -> list[dict]:
        return self._request("GET", f"/api/projects/{project_id}/export")  # type: ignore[list-item]

    # ---------- webhooks ----------

    def create_webhook(self, project_id: int, url: str, actions: list[str]) -> dict:
        return self._request(  # type: ignore[return-value]
            "POST",
            "/api/webhooks/",
            json={
                "project": project_id,
                "url": url,
                "send_payload": True,
                "send_for_all_actions": False,
                "actions": actions,
                "is_active": True,
            },
        )

    def list_webhooks(self, project_id: int) -> list[dict]:
        return self._request("GET", "/api/webhooks/", params={"project": project_id})  # type: ignore[list-item]

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

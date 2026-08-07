"""Label Studio API 客户端封装：从 .env 读取连接配置，提供鉴权的 REST 调用。

供 importer / exporter / 编排层复用。"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from ..common.config import PROJECT_ROOT, get_settings

# 触发 .env 加载（config 已 setdefault 环境变量）
get_settings()


class LSClient:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url or os.environ.get("LABEL_STUDIO_URL", "http://127.0.0.1:8300")).rstrip("/")
        self.token = token or os.environ.get("LABEL_STUDIO_API_KEY", "")
        if not self.token:
            raise RuntimeError("LABEL_STUDIO_API_KEY 未设置，请先运行 src.ls_platform.bootstrap")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Token {self.token}"})

    def _check(self, r: requests.Response, what: str):
        if r.status_code >= 400:
            raise RuntimeError(f"LS {what} 失败: {r.status_code} {r.text[:300]}")
        return r

    def whoami(self) -> dict:
        return self._check(self.s.get(f"{self.url}/api/current-user/whoami", timeout=30), "whoami").json()

    def list_projects(self) -> list[dict]:
        r = self._check(self.s.get(f"{self.url}/api/projects/", params={"page_size": 100}, timeout=30), "list_projects")
        return r.json().get("results", [])

    def get_project(self, pid: int) -> dict:
        return self._check(self.s.get(f"{self.url}/api/projects/{pid}", timeout=30), "get_project").json()

    def create_project(self, title: str, label_config: str, description: str = "") -> dict:
        r = self._check(self.s.post(
            f"{self.url}/api/projects/",
            json={"title": title, "label_config": label_config, "description": description},
            timeout=60), "create_project")
        return r.json()

    def delete_project(self, pid: int) -> None:
        self._check(self.s.delete(f"{self.url}/api/projects/{pid}", timeout=30), "delete_project")

    def import_files(self, pid: int, files: list[tuple[str, bytes]], meta_list: list[dict] | None = None) -> dict:
        """以 multipart 上传图片文件，创建 task。

        files: [(filename, bytes), ...]
        返回原始响应 dict（含 task_count / file_upload_ids）。
        注意：LS 会自动创建 task，其 data.image 绑定到上传文件；需随后按文件名查找 task id。
        """
        file_tuples = [("files", (fn, data, "image/jpeg")) for fn, data in files]
        r = self._check(self.s.post(
            f"{self.url}/api/projects/{pid}/import",
            files=file_tuples, timeout=300), "import_files")
        return r.json() if isinstance(r.json(), dict) else {"raw": r.json()}

    def find_task_by_image(self, pid: int, filename_suffix: str) -> dict | None:
        """在项目 task 中查找 data.image 以 filename_suffix 结尾的 task。"""
        page = 1
        while True:
            r = self._check(self.s.get(
                f"{self.url}/api/projects/{pid}/tasks",
                params={"page": page, "page_size": 100}, timeout=60), "list_tasks")
            d = r.json()
            tasks = d if isinstance(d, list) else d.get("tasks", d.get("results", []))
            if not tasks:
                return None
            for t in tasks:
                img = (t.get("data") or {}).get("image", "")
                if img.endswith(filename_suffix):
                    return t
            # 无分页信息则只查第一页
            if isinstance(d, list) or "next" not in d:
                return None
            if not d.get("next"):
                return None
            page += 1

    def index_task_images(self, pid: int) -> dict:
        """RA-015：一次性分页遍历全部 task，建立 data.image 文件名 → task 索引。

        导入前只建一次索引（O(N)），代替每上传一张就分页搜索的 O(N²) 模式；
        同时提供幂等判重键（同名文件已存在 → 跳过，不重复创建）。"""
        index: dict[str, dict] = {}
        page = 1
        while True:
            d = self.list_tasks(pid, page=page, page_size=100)
            tasks = d if isinstance(d, list) else d.get("tasks", d.get("results", []))
            for t in tasks:
                img = (t.get("data") or {}).get("image", "")
                if img:
                    index[img.rsplit("/", 1)[-1]] = t
            if isinstance(d, list):
                break
            if "next" not in d or not d.get("next"):
                break
            page += 1
        return index

    def delete_all_tasks(self, pid: int) -> None:
        self._check(self.s.delete(f"{self.url}/api/projects/{pid}/tasks", timeout=120), "delete_all_tasks")

    def import_tasks(self, pid: int, tasks: list[dict]) -> list[dict]:
        """以 JSON 导入 task（每个含 data/meta/predictions）。"""
        r = self._check(self.s.post(
            f"{self.url}/api/projects/{pid}/import",
            json=tasks, timeout=300), "import_tasks")
        data = r.json()
        return data.get("tasks", data) if isinstance(data, dict) else data

    def list_tasks(self, pid: int, page: int = 1, page_size: int = 100) -> dict:
        # 尾斜杠端点才支持 ?page= 分页（无尾斜杠版 page>1 会 404）
        r = self._check(self.s.get(
            f"{self.url}/api/projects/{pid}/tasks/",
            params={"page": page, "page_size": page_size}, timeout=60), "list_tasks")
        return r.json()

    def create_prediction(self, task_id: int, result: list[dict], score: float = 0.5,
                          model_version: str = "yolo", meta: dict | None = None) -> dict:
        payload = {"task": task_id, "result": result, "score": score,
                   "model_version": model_version}
        if meta:
            payload["meta"] = meta
        r = self._check(self.s.post(
            f"{self.url}/api/predictions/",
            json=payload,
            timeout=60), "create_prediction")
        return r.json()

    def get_task(self, task_id: int) -> dict:
        """GET 单个 task（含 predictions/annotations，回填扫描用）。"""
        return self._check(self.s.get(
            f"{self.url}/api/tasks/{task_id}", timeout=60), "get_task").json()

    def update_task_meta(self, task_id: int, patch: dict) -> dict:
        """合并式更新 task meta（不碰 predictions/annotations）。

        用于 no_proposal 等治理标记（GLTC Task 4）；合并而非替换，
        保留既有 photo_id/sha256 等 meta 字段。"""
        current = self.get_task(task_id).get("meta") or {}
        merged = {**current, **patch}
        return self._check(self.s.patch(
            f"{self.url}/api/tasks/{task_id}/",
            json={"meta": merged}, timeout=60), "update_task_meta").json()

    def fetch_file(self, path_or_url: str) -> bytes:
        """带鉴权下载 LS 托管文件（data.image 相对路径或绝对 URL）。"""
        url = path_or_url if path_or_url.startswith("http") else f"{self.url}{path_or_url}"
        return self._check(self.s.get(url, timeout=120), "fetch_file").content

    def export(self, pid: int, export_type: str = "JSON") -> list[dict]:
        r = self._check(self.s.get(
            f"{self.url}/api/projects/{pid}/export",
            params={"exportType": export_type}, timeout=300), "export")
        return r.json()

    def file_url(self, upload_path: str) -> str:
        """把 LS 上传返回的相对路径补全为绝对 URL。"""
        if upload_path.startswith("http"):
            return upload_path
        return f"{self.url}{upload_path}"

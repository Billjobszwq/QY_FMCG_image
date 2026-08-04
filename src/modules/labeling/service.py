"""Label Studio 闭环服务（M4）：assisted/blind 项目分离、导入、webhook 收件箱、API 对账。

设计原则（手册 M4）：
- assisted 项目携带预标注 prediction；blind 项目绝不写入任何 prediction（盲标）；
- webhook inbox 幂等去重（source, event_id 唯一），不依赖 webhook 单点成功；
- 对账（reconcile）以 LS API 为事实源，inbox 仅作事件留痕，两边数量不一致时显式标记。
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from typing import Any, Iterable

WEBHOOK_ACTIONS = [
    "ANNOTATION_CREATED",
    "ANNOTATION_UPDATED",
    "ANNOTATIONS_DELETED",
    "TASKS_CREATED",
    "TASKS_DELETED",
]


class LabelingError(Exception):
    pass


def canonical_event_id(action: str, payload: dict[str, Any]) -> str:
    """无 X-Event-Id 时的确定性事件指纹：action + 关键实体 + 更新时间。"""
    ann = payload.get("annotation") or {}
    task = payload.get("task") or {}
    if isinstance(task, int):
        task_id, updated = task, ""
    else:
        task_id, updated = task.get("id"), task.get("updated_at") or ann.get("updated_at") or ""
    key = json.dumps(
        {"action": action, "annotation_id": ann.get("id"), "task_id": task_id, "updated_at": updated},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def box_px_to_ls_result(
    box_px: tuple[float, float, float, float],
    width: int,
    height: int,
    *,
    label: str = "product",
    region_id: str | None = None,
) -> dict[str, Any]:
    """像素框 (x1,y1,x2,y2) → LS rectanglelabels 百分比 result。越界裁剪到 [0,100]。"""
    x1, y1, x2, y2 = box_px
    if width <= 0 or height <= 0:
        raise LabelingError(f"非法图片尺寸: {width}x{height}")
    px = max(0.0, min(x1, width)) / width * 100.0
    py = max(0.0, min(y1, height)) / height * 100.0
    pw = max(0.0, min(x2, width)) / width * 100.0 - px
    ph = max(0.0, min(y2, height)) / height * 100.0 - py
    if pw <= 0 or ph <= 0:
        raise LabelingError(f"非法框: {box_px}")
    return {
        "id": region_id or f"pred_{uuid.uuid4().hex[:12]}",
        "from_name": "box",
        "to_name": "image",
        "type": "rectanglelabels",
        "value": {
            "x": round(px, 4),
            "y": round(py, 4),
            "width": round(pw, 4),
            "height": round(ph, 4),
            "rotation": 0,
            "rectanglelabels": [label],
        },
    }


def image_size(data: bytes) -> tuple[int, int]:
    """JPEG/PNG 尺寸解析（不引入重依赖时退回 PIL）。"""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        return im.width, im.height


def predictions_from_recognition(
    recognition: Any,
    photos: list[tuple[str, bytes]],
    *,
    model_version: str,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """用识别能力（8091）为 assisted 项目生成预标注（真实模型，非 mock）。

    单图失败不阻塞整体；返回 (按文件名的 prediction 列表, 失败数)。"""
    out: dict[str, list[dict[str, Any]]] = {}
    failures = 0
    for name, data in photos:
        try:
            width, height = image_size(data)
            result = recognition.recognize(data)
            results = []
            for p in result.get("products", []):
                box = p.get("box")
                if not box or len(box) != 4:
                    continue
                results.append(
                    {
                        "score": float(p.get("confidence") or 0.0),
                        "model_version": model_version,
                        "result": [
                            box_px_to_ls_result(
                                tuple(float(v) for v in box), width, height
                            )
                        ],
                    }
                )
            if results:
                out[name] = results
        except Exception:  # noqa: BLE001 — 单图失败不阻塞导入
            failures += 1
    return out, failures


class LabelingService:
    def __init__(
        self,
        store: Any,
        ls: Any,
        *,
        webhook_url_base: str = "http://127.0.0.1:8400",
    ):
        self.store = store
        self.ls = ls
        self.webhook_url_base = webhook_url_base.rstrip("/")

    # ---------- batch / projects ----------

    def create_batch(self, name: str, label_config: str) -> dict[str, Any]:
        """创建 assisted + blind 双项目批次。两者 label_config 相同，但只有 assisted 后续会写 prediction。"""
        assisted = self.ls.create_project(
            f"{name} [assisted]",
            label_config,
            description="辅助标注：可见模型预标注 prediction（自动框仅作起点）",
        )
        blind = self.ls.create_project(
            f"{name} [blind]",
            label_config,
            description="盲标：不提供任何模型 prediction，用于无偏对照",
        )
        batch = self.store.create_labeling_batch(
            batch_id=uuid.uuid4().hex,
            name=name,
            assisted_project_id=int(assisted["id"]),
            blind_project_id=int(blind["id"]),
        )
        # webhook 注册（fail-open：失败不阻塞，对账机制兜底）
        webhook_ids: list[int] = []
        webhook_error: str | None = None
        try:
            for pid in (int(assisted["id"]), int(blind["id"])):
                wh = self.ls.create_webhook(
                    pid, f"{self.webhook_url_base}/api/v1/webhooks/label-studio", WEBHOOK_ACTIONS
                )
                webhook_ids.append(int(wh["id"]))
        except Exception as e:  # noqa: BLE001 — webhook 失败由对账兜底
            webhook_error = str(e)
        return {
            "batch": batch,
            "assisted_project_id": int(assisted["id"]),
            "blind_project_id": int(blind["id"]),
            "webhook_ids": webhook_ids,
            "webhook_error": webhook_error,
        }

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        return self.store.get_labeling_batch(batch_id)

    def list_batches(self) -> list[dict[str, Any]]:
        return self.store.list_labeling_batches()

    # ---------- import ----------

    def import_photos(
        self,
        batch_id: str,
        photos: list[tuple[str, bytes]],
        *,
        assisted_predictions: dict[str, list[dict[str, Any]]] | None = None,
        model_version: str = "unspecified",
    ) -> dict[str, Any]:
        """同一组照片导入双项目；assisted 侧按文件名写入 prediction；blind 侧绝不写 prediction。"""
        if not photos:
            raise LabelingError("导入照片为空")
        batch = self.store.get_labeling_batch(batch_id)
        assisted_pid, blind_pid = batch["assisted_project_id"], batch["blind_project_id"]
        if assisted_pid is None or blind_pid is None:
            raise LabelingError(f"batch {batch_id} 项目未就绪")

        a_resp = self.ls.import_files(int(assisted_pid), photos)
        b_resp = self.ls.import_files(int(blind_pid), photos)

        assisted_tasks = self.ls.list_tasks(int(assisted_pid))
        blind_tasks = self.ls.list_tasks(int(blind_pid))

        # assisted prediction 按上传文件名匹配 task（LS upload URL 保留原始文件名）
        pred_written = 0
        if assisted_predictions:
            for task in assisted_tasks:
                image_url = (task.get("data") or {}).get("image", "")
                matched = next(
                    (fn for fn in assisted_predictions if image_url.endswith(fn)), None
                )
                if matched:
                    results = assisted_predictions[matched]
                    if results:
                        score = max(float(r.get("score", 0.0)) for r in results)
                        # 展平：每项可能是单个 region dict 或 region 列表；
                        # 直接嵌套列表会被 LS 校验拒绝（实测 400 Validation error）。
                        flat: list[dict[str, Any]] = []
                        for r in results:
                            part = r["result"] if "result" in r else r
                            if isinstance(part, list):
                                flat.extend(part)
                            else:
                                flat.append(part)
                        self.ls.create_prediction(
                            int(task["id"]),
                            flat,
                            score=score,
                            model_version=model_version,
                        )
                        pred_written += 1

        self.store.update_labeling_batch(
            batch_id, task_count=len(photos), status="imported"
        )
        return {
            "batch_id": batch_id,
            "assisted": {"project_id": assisted_pid, "imported": a_resp.get("task_count", len(photos))},
            "blind": {"project_id": blind_pid, "imported": b_resp.get("task_count", len(photos))},
            "assisted_tasks": len(assisted_tasks),
            "blind_tasks": len(blind_tasks),
            "predictions_written": pred_written,
        }

    # ---------- webhook inbox ----------

    def ingest_webhook(
        self, payload: dict[str, Any], *, event_id: str | None = None
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "UNKNOWN")
        project = payload.get("project")
        project_id = project.get("id") if isinstance(project, dict) else project
        task = payload.get("task")
        task_id = task.get("id") if isinstance(task, dict) else (task if isinstance(task, int) else None)
        eid = event_id or canonical_event_id(action, payload)
        accepted = self.store.record_webhook_event(
            source="label_studio",
            event_id=eid,
            action=action,
            project_id=int(project_id) if project_id is not None else None,
            task_id=int(task_id) if task_id is not None else None,
            payload=payload,
        )
        return {"accepted": accepted, "event_id": eid, "action": action}

    def inbox(self, project_id: int | None = None) -> list[dict[str, Any]]:
        return self.store.list_webhook_events(source="label_studio", project_id=project_id)

    # ---------- reconcile ----------

    _ANNOTATION_ACTIONS = {"ANNOTATION_CREATED", "ANNOTATION_UPDATED"}

    def reconcile(self, batch_id: str) -> dict[str, Any]:
        """API 对账：LS API 为事实源，inbox 为事件留痕；不一致时显式标记，绝不静默。"""
        batch = self.store.get_labeling_batch(batch_id)
        report: dict[str, Any] = {"batch_id": batch_id, "projects": {}}
        all_consistent = True
        for role in ("assisted", "blind"):
            pid = batch[f"{role}_project_id"]
            if pid is None:
                continue
            tasks = self.ls.list_tasks(int(pid))
            annotations_api = sum(int(t.get("total_annotations") or 0) for t in tasks)
            predictions_api = sum(int(t.get("total_predictions") or 0) for t in tasks)
            events = self.store.list_webhook_events(source="label_studio", project_id=int(pid))
            ann_events = [e for e in events if e["action"] in self._ANNOTATION_ACTIONS]
            entry = {
                "project_id": pid,
                "tasks": len(tasks),
                "annotations_api": annotations_api,
                "predictions_api": predictions_api,
                "inbox_events": len(events),
                "inbox_annotation_events": len(ann_events),
                # 严格一致 = API 标注数与 inbox 去重后标注事件数相等；
                # 不等时两列数字都保留（webhook 可能丢/重发，API 为事实源）
                "consistent": annotations_api == len(ann_events),
            }
            report["projects"][role] = entry
            all_consistent = all_consistent and entry["consistent"]
        report["consistent"] = all_consistent
        # 盲标项目必须 0 prediction（分离红线）
        blind = report["projects"].get("blind", {})
        report["blind_no_predictions"] = blind.get("predictions_api", 0) == 0
        if report["blind_no_predictions"]:
            self.store.update_labeling_batch(batch_id, status="reconciled")
        return report

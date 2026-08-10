"""导入 micro-gold v2 到 LS 新盲审项目（classification-region 模式）。

先 10 条验收批（3 canonical/2 pending/2 hard/2 negative/1 bad-crop 候选），
通过后再幂等放量 200。taxonomy 含 canonical+pending+状态选项
（bad_crop/background/unknown/unreadable/conflict）。无 prediction。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

env = dict(l.strip().split("=", 1) for l in open(ROOT / ".env")
           if l.strip() and "=" in l and not l.startswith("#"))
KEY = env["LABEL_STUDIO_API_KEY"]
BASE = "http://127.0.0.1:8300"


def req(path, body=None, method="GET"):
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Token {KEY}",
                 "Content-Type": "application/json"}, method=method)
    return json.loads(urllib.request.urlopen(r, timeout=120).read())


EXTRA_CHOICES = ["bad_crop", "background_no_product", "unknown",
                 "unreadable", "conflict", "new_packaging_new_name",
                 "new_packaging_old_name"]


def build_config() -> str:
    cfg = req("/api/projects/19/")["label_config"]
    # 在 status Choices 前插入额外选项
    extra = "".join(f'\n    <Choice value="{c}" />' for c in EXTRA_CHOICES)
    cfg = cfg.replace('<Choices name="status"', extra + '\n  <Choices name="status"')
    return cfg


def task_payload(t: dict) -> dict:
    img = (ROOT / ".micro_gold_v2/images" / t["anonymous_image_name"])
    b = base64.b64encode(img.read_bytes()).decode()
    return {"data": {"image": f"data:image/jpeg;base64,{b}",
                     "sample_id": t["micro_gold_task_id"],
                     "stratum": t["stratum"]}}


def main() -> int:
    man = json.loads((ROOT / ".micro_gold_v2/manifest.json").read_text())
    tasks = man["tasks"]
    # 验收批 10 条
    pick = {"canonical": 3, "pending": 2, "hard": 2, "negative": 2}
    acc = []
    for st, n in pick.items():
        acc += [t for t in tasks if t["stratum"] == st][:n]
    acc += [t for t in tasks if t["stratum"] == "hard"][:0]
    acc = acc[:9] + [tasks[0]]
    acc = acc[:10]
    existing = req("/api/projects?search=demo_micro_gold_v2")
    proj = None
    for p in existing.get("results", existing if isinstance(
            existing, list) else []):
        if "demo_micro_gold_v2" in p.get("title", ""):
            proj = p
    if proj is None:
        proj = req("/api/projects/", {
            "title": "demo_micro_gold_v2_blind",
            "label_config": build_config(), "is_draft": False}, "POST")
    pid = proj["id"]
    cur = req(f"/api/projects/{pid}/tasks/?pageSize=1000")
    cur_n = len(cur.get("tasks", cur) if isinstance(cur, dict) else cur)
    if cur_n == 0:
        req(f"/api/projects/{pid}/import",
            [task_payload(t) for t in acc], "POST")
        print("acceptance batch imported: 10, project:", pid)
    elif cur_n == 10:
        rest = [t for t in tasks if t["micro_gold_task_id"] not in
                {x["data"].get("sample_id") for x in (
                    cur.get("tasks", cur) if isinstance(cur, dict)
                    else cur)}]
        req(f"/api/projects/{pid}/import",
            [task_payload(t) for t in rest], "POST")
        print("full import done:", len(rest), "project:", pid)
    else:
        print("already full:", cur_n)
    (ROOT / ".micro_gold_v2/ls_project.json").write_text(
        json.dumps({"project_id": pid}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

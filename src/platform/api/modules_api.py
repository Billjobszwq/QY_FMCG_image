"""API 预留：模块注册表。新模块 = manifest 注册（不改数据架构）。"""
from __future__ import annotations

from fastapi import APIRouter

MODULES = [
    {"module_id": "overview", "name": "总览·主管", "color": "#ab54f7",
     "agent": "supervisor-agent", "api_prefix": "/api/v1/",
     "status": "live"},
    {"module_id": "recognition", "name": "图像识别", "color": "#16a6ff",
     "agent": "recognition-agent", "api_prefix": "/api/v1/recognition",
     "status": "live"},
    {"module_id": "annotation", "name": "标注中心", "color": "#1be349",
     "agent": "annotation-agent", "api_prefix": "/api/v1/labelstudio",
     "status": "live"},
    {"module_id": "data", "name": "数据仓库", "color": "#ffdb08",
     "agent": "data-agent", "api_prefix": "/api/v1/assets",
     "status": "live"},
    {"module_id": "training", "name": "模型训练", "color": "#ff8e0a",
     "agent": "modelops-agent", "api_prefix": "/api/v1/training",
     "status": "live"},
    {"module_id": "workflow", "name": "工作流编排", "color": "#c79dfc",
     "agent": "workflow-agent", "api_prefix": "/api/v1/workflows",
     "status": "live"},
    {"module_id": "biz", "name": "经营智能", "color": "#ea3737",
     "agent": "biz-agent", "api_prefix": "/api/v1/biz",
     "status": "planned",
     "submodules": ["BI 报表", "数据告警", "财务对账", "地理位置分析",
                    "线库规划", "问卷设置", "数据深度对话", "策略分析"]},
    {"module_id": "system", "name": "系统", "color": "#00aa3c",
     "agent": "system-agent", "api_prefix": "/api/v1/system",
     "status": "live"},
]


def create_modules_router() -> APIRouter:
    router = APIRouter(tags=["modules"])

    @router.get("/api/v1/biz/m3bars")
    def m3bars() -> dict:
        import json as _j
        from pathlib import Path as _P
        bars = []
        for e in ("e1", "e2", "e3", "e4", "e5"):
            f = _P(f".models/m3_ablation_{e}_v1/train_report.json")
            v = 0.0
            if f.exists():
                v = _j.loads(f.read_text()).get("final", {}) \
                    .get("top1", 0.0)
            bars.append({"k": e.upper(), "v": round(v, 4)})
        return {"bars": bars}

    @router.get("/api/v1/modules")
    def modules() -> dict:
        return {"count": len(MODULES), "modules": MODULES,
                "contract": "新模块注册 manifest 即得 API 前缀/色系/agent，"
                            "不修改底层数据架构"}

    return router

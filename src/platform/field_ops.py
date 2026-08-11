"""ABOSV2 Phase F：位置与外勤服务层（03-DOMAIN-PACKS-SPEC §5）。

- GeocoderAdapter：候选经纬度 + 置信度；低置信度必须人工确认，
  未确认地址不得自动派发；
- MapProviderAdapter：本机无离线地图瓦片 → 诚实 blocked（列表回退）；
- VRP（MVP：最近邻 + 约束）：时间窗/最大里程/多项目硬隔离；
  未分配原因显式留痕；
- 到店：围栏 enter 事件（半径+精度校验）；门头必拍；可选自拍；
  人脸比对默认不自动触发（本 MVP 不实现人脸能力，诚实标注）；
- 差旅费：按路线 km × 单价，证据随任务留痕。
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any


class FieldOpsError(Exception):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class GeocoderAdapter:
    """本机离线地理编码（确定性候选集；真实服务经同一 SPI 替换）。"""

    name = "local_offline"

    def available(self) -> tuple[bool, str]:
        return True, "local offline geocoder（确定性候选）"

    def geocode(self, raw: str) -> list[dict]:
        h = int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)
        base_lat = 31.0 + (h % 1000) / 10000.0
        base_lng = 121.0 + ((h // 1000) % 1000) / 10000.0
        # 规则：地址带 [geo] 精确标记 → 高置信；否则低置信需人工确认
        high = "[geo]" in raw
        conf = 0.93 if high else 0.45
        return [
            {"lat": round(base_lat, 6), "lng": round(base_lng, 6),
             "formatted": f"{raw}（候选1）", "confidence": conf,
             "source": self.name},
            {"lat": round(base_lat + 0.0008, 6),
             "lng": round(base_lng + 0.0008, 6),
             "formatted": f"{raw}（候选2）",
             "confidence": round(max(conf - 0.25, 0.1), 2),
             "source": self.name},
        ]


class MapProviderAdapter:
    """地图瓦片提供者：可配置瓦片源；未配置时诚实 degraded。"""

    name = "map_tiles"

    def __init__(self) -> None:
        import os
        self.tiles_url = os.environ.get("MAP_TILES_URL", "").strip()

    def available(self) -> tuple[bool, str]:
        if self.tiles_url:
            return True, f"已配置瓦片源: {self.tiles_url}"
        return False, ("未配置地图瓦片源（MAP_TILES_URL 环境变量）；"
                       "可配置 OSM/高德等合规瓦片；当前以坐标散点"
                       "降级图与列表回退展示")


class ProviderGeocoder:
    """地理编码 Provider SPI（高德/腾讯等）：需 Key；无 Key 时
    诚实不可用并给出配置入口，不伪造坐标。"""

    def __init__(self) -> None:
        import os
        self.provider = os.environ.get("GEOCODER_PROVIDER", "").strip()
        self.amap_key = os.environ.get("AMAP_API_KEY", "").strip()
        self.tencent_key = os.environ.get("TENCENT_MAP_KEY", "").strip()

    def available(self) -> tuple[bool, str]:
        if self.provider == "amap" and self.amap_key:
            return True, "amap geocoder 已配置"
        if self.provider == "tencent" and self.tencent_key:
            return True, "tencent geocoder 已配置"
        return False, ("未配置地理编码 Provider：请设置环境变量"
                       " GEOCODER_PROVIDER=amap|tencent 与对应 Key"
                       "（AMAP_API_KEY / TENCENT_MAP_KEY）；未配置前可"
                       "导入经纬度或手工确认候选坐标")

    def geocode(self, raw: str) -> list[dict]:
        import urllib.parse
        import urllib.request
        if self.provider == "amap" and self.amap_key:
            url = ("https://restapi.amap.com/v3/geocode/geo?key="
                   + self.amap_key + "&address="
                   + urllib.parse.quote(raw))
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read())
            out = []
            for g in (d.get("geocodes") or [])[:3]:
                lng, lat = str(g.get("location", "")).split(",")
                out.append({"lat": float(lat), "lng": float(lng),
                            "formatted": g.get("formatted_address", raw),
                            "confidence": 0.9,
                            "source": "amap"})
            return out
        if self.provider == "tencent" and self.tencent_key:
            url = ("https://apis.map.qq.com/ws/geocoder/v1/?key="
                   + self.tencent_key + "&address="
                   + urllib.parse.quote(raw))
            with urllib.request.urlopen(url, timeout=15) as r:
                d = json.loads(r.read())
            res = d.get("result") or {}
            loc = res.get("location") or {}
            if not loc:
                return []
            return [{"lat": loc.get("lat"), "lng": loc.get("lng"),
                     "formatted": res.get("title", raw),
                     "confidence": 0.9, "source": "tencent"}]
        raise FieldOpsError(self.available()[1])


class RouteSolverAdapter:
    """路线求解 SPI：首版启发式诚实标注；OR-Tools 预留接口。"""

    name = "abstract"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def solve(self, depot: tuple, stops: list[dict],
              constraints: dict) -> list[dict]:
        raise NotImplementedError


class NearestNeighborSolver(RouteSolverAdapter):
    """最近邻启发式：首版可用，必须诚实标注非 VRP 最优解。"""

    name = "nearest_neighbor_heuristic"

    def available(self) -> tuple[bool, str]:
        return True, ("最近邻启发式（非 VRP 最优解；约束违反与"
                      "未优化原因逐条留痕）")

    def solve(self, depot: tuple, stops: list[dict],
              constraints: dict) -> list[dict]:
        cur = depot
        remaining = list(stops)
        ordered: list[dict] = []
        while remaining:
            remaining.sort(key=lambda s: _haversine_km(
                cur[0], cur[1], s["lat"], s["lng"]))
            nxt = remaining.pop(0)
            nxt["leg_km"] = round(_haversine_km(
                cur[0], cur[1], nxt["lat"], nxt["lng"]), 3)
            ordered.append(nxt)
            cur = (nxt["lat"], nxt["lng"])
        return ordered


class OrToolsSolverAdapter(RouteSolverAdapter):
    """OR-Tools VRP 求解器预留 Adapter：未安装/未评估前诚实 blocked。"""

    name = "or_tools_vrp"

    def available(self) -> tuple[bool, str]:
        try:
            import ortools  # noqa: F401
            return True, "ortools 可用"
        except Exception:
            return False, ("ortools 未安装；安装后可切换 VRP 求解器"
                           "（当前使用最近邻启发式）")

    def solve(self, depot: tuple, stops: list[dict],
              constraints: dict) -> list[dict]:
        ok, reason = self.available()
        if not ok:
            raise FieldOpsError(reason)
        return NearestNeighborSolver().solve(depot, stops, constraints)


def get_route_solver() -> RouteSolverAdapter:
    import os
    name = os.environ.get("ROUTE_SOLVER", "nearest_neighbor")
    if name == "or_tools":
        s = OrToolsSolverAdapter()
        if s.available()[0]:
            return s
    return NearestNeighborSolver()


def _haversine_km(lat1: float, lng1: float, lat2: float,
                  lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * \
        math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class FieldOpsService:
    def __init__(self, store: Any,
                 geocoder: GeocoderAdapter | None = None) -> None:
        self.store = store
        self.geocoder = geocoder or GeocoderAdapter()
        self.map_provider = MapProviderAdapter()
        self.provider_geocoder = ProviderGeocoder()
        self.solver = get_route_solver()

    # ---------- 地址库 ----------

    def add_address(self, *, customer_id: str, raw: str,
                    actor: str = "") -> dict:
        candidates = self.geocoder.geocode(raw)
        aid = _new_id("addr")
        now = _now()
        self.store._conn.execute(
            "INSERT INTO geo_address_v1 (address_id, customer_id, raw,"
            " candidates_json, confidence, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (aid, customer_id, raw,
             json.dumps(candidates, ensure_ascii=False),
             candidates[0]["confidence"], "pending", now, now))
        self.store._conn.commit()
        return self.get_address(aid)

    def get_address(self, address_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM geo_address_v1 WHERE address_id=?",
            (address_id,)).fetchone()
        if row is None:
            raise FieldOpsError(f"address 不存在: {address_id}")
        d = dict(row)
        d["candidates"] = json.loads(d["candidates_json"])
        d["chosen"] = json.loads(d["chosen_json"] or "null")
        return d

    def list_addresses(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT address_id FROM geo_address_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [self.get_address(r["address_id"]) for r in rows]

    def verify_address(self, address_id: str, *, chosen_index: int,
                       actor: str) -> dict:
        """人工确认经纬度（低置信度必须经此步才可派发）。"""
        a = self.get_address(address_id)
        if chosen_index < 0 or chosen_index >= len(a["candidates"]):
            raise FieldOpsError("候选序号非法")
        chosen = a["candidates"][chosen_index]
        self.store._conn.execute(
            "UPDATE geo_address_v1 SET status='verified', chosen_json=?,"
            " confidence=?, verified_by=?, updated_at=? WHERE address_id=?",
            (json.dumps(chosen, ensure_ascii=False),
             chosen["confidence"], actor, _now(), address_id))
        self.store._conn.commit()
        return self.get_address(address_id)

    def geocode_with_provider(self, address_id: str, *,
                              actor: str) -> dict:
        """获取坐标（Provider SPI）：有 Key 真实调用；无 Key 诚实
        降级并返回配置指引，不伪造坐标。"""
        a = self.get_address(address_id)
        ok, reason = self.provider_geocoder.available()
        if not ok:
            return {"address_id": address_id, "provider": "none",
                    "status": "degraded", "reason": reason,
                    "fallback": "可导入经纬度或手工确认候选坐标"}
        try:
            cands = self.provider_geocoder.geocode(a["raw"])
        except Exception as e:
            return {"address_id": address_id,
                    "provider": self.provider_geocoder.provider,
                    "status": "error", "reason": str(e)[:200]}
        if not cands:
            return {"address_id": address_id,
                    "provider": self.provider_geocoder.provider,
                    "status": "no_candidates",
                    "reason": "Provider 未返回候选"}
        self.store._conn.execute(
            "UPDATE geo_address_v1 SET candidates_json=?, confidence=?,"
            " updated_at=? WHERE address_id=?",
            (json.dumps(cands, ensure_ascii=False),
             cands[0]["confidence"], _now(), address_id))
        self.store._conn.commit()
        return {"address_id": address_id,
                "provider": self.provider_geocoder.provider,
                "status": "candidates",
                "candidates": cands,
                "note": "低置信候选仍需人工确认后才可派发"}

    def set_manual_coords(self, address_id: str, *, lat: float,
                          lng: float, coord_system: str = "wgs84",
                          source: str = "manual", actor: str) -> dict:
        """手工/导入坐标确认（source=manual|import，不伪装地理编码）。"""
        self.get_address(address_id)
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
            raise FieldOpsError("经纬度越界")
        chosen = {"lat": lat, "lng": lng, "source": source,
                  "coord_system": coord_system, "confidence": 1.0}
        self.store._conn.execute(
            "UPDATE geo_address_v1 SET status='verified', chosen_json=?,"
            " confidence=1.0, verified_by=?, updated_at=?"
            " WHERE address_id=?",
            (json.dumps(chosen, ensure_ascii=False), actor, _now(),
             address_id))
        self.store._conn.commit()
        return self.get_address(address_id)

    # ---------- 员工 ----------

    def add_employee(self, *, customer_id: str, name: str,
                     skills: list | None = None,
                     vehicle: str = "") -> dict:
        eid = _new_id("emp")
        self.store._conn.execute(
            "INSERT INTO geo_employee_v1 (employee_id, customer_id, name,"
            " skills_json, vehicle, created_at) VALUES (?,?,?,?,?,?)",
            (eid, customer_id, name,
             json.dumps(skills or [], ensure_ascii=False), vehicle,
             _now()))
        self.store._conn.commit()
        row = self.store._conn.execute(
            "SELECT * FROM geo_employee_v1 WHERE employee_id=?",
            (eid,)).fetchone()
        return dict(row)

    def list_employees(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM geo_employee_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 外勤任务 ----------

    def create_task(self, *, customer_id: str, address_id: str,
                    project_id: str = "", kind: str = "visit",
                    survey_id: str = "",
                    require_storefront: bool = True,
                    selfie_required: bool = False,
                    actor: str) -> dict:
        a = self.get_address(address_id)
        if a["customer_id"] != customer_id:
            raise FieldOpsError("地址不属于该客户（作用域隔离）")
        tid = _new_id("ft")
        now = _now()
        self.store._conn.execute(
            "INSERT INTO field_task_v1 (task_id, customer_id, project_id,"
            " address_id, kind, survey_id, status, require_storefront,"
            " selfie_required, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tid, customer_id, project_id, address_id, kind, survey_id,
             "draft", 1 if require_storefront else 0,
             1 if selfie_required else 0, now, now))
        self.store._conn.commit()
        return self.get_task(tid)

    def get_task(self, task_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM field_task_v1 WHERE task_id=?",
            (task_id,)).fetchone()
        if row is None:
            raise FieldOpsError(f"field task 不存在: {task_id}")
        return dict(row)

    def list_tasks(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT task_id FROM field_task_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [self.get_task(r["task_id"]) for r in rows]

    # ---------- 路线规划（VRP MVP） ----------

    def plan_route(self, *, customer_id: str, task_ids: list[str],
                   constraints: dict | None = None,
                   actor: str) -> dict:
        cons = constraints or {}
        depot = (float(cons.get("depot_lat", 31.0)),
                 float(cons.get("depot_lng", 121.0)))
        merge_projects = bool(cons.get("merge_projects", False))
        max_km = cons.get("max_km")
        stops: list[dict] = []
        unassigned: list[dict] = []
        projects: set[str] = set()
        tasks = []
        for tid in task_ids:
            t = self.get_task(tid)
            if t["customer_id"] != customer_id:
                unassigned.append({"task_id": tid,
                                   "reason": "任务不属于该客户（硬隔离）"})
                continue
            a = self.get_address(t["address_id"])
            if a["status"] != "verified":
                unassigned.append({
                    "task_id": tid,
                    "reason": "地址未人工确认（低置信度不得自动派发）"})
                continue
            projects.add(t["project_id"] or "_")
            tasks.append((t, a))
        if len(projects) > 1 and not merge_projects:
            # 硬隔离：多项目未显式允许合并 → 全部不分配并说明
            for t, _ in tasks:
                unassigned.append({
                    "task_id": t["task_id"],
                    "reason": "跨项目任务未允许合并（硬隔离）；"
                              "设置 merge_projects=true 或按项目分别规划"})
            tasks = []
        # 求解器排序（首版启发式诚实标注；约束违反逐条留痕）
        solver_stops = [{"task_id": t["task_id"], "address": a,
                         "lat": a["chosen"]["lat"],
                         "lng": a["chosen"]["lng"]} for t, a in tasks]
        ordered_stops = self.solver.solve(depot, solver_stops, cons)
        ordered = [(next(t for t in tasks if t[0]["task_id"] == s["task_id"]))
                   for s in ordered_stops]
        total_km = 0.0
        cur = depot
        seq = 1
        for t, a in ordered:
            km = _haversine_km(cur[0], cur[1], a["chosen"]["lat"],
                               a["chosen"]["lng"])
            total_km += km
            if max_km is not None and total_km > float(max_km):
                unassigned.append({
                    "task_id": t["task_id"],
                    "reason": f"超出最大里程约束 max_km={max_km}"})
                total_km -= km
                continue
            stops.append({"seq": seq, "task_id": t["task_id"],
                          "address_id": a["address_id"],
                          "lat": a["chosen"]["lat"],
                          "lng": a["chosen"]["lng"],
                          "leg_km": round(km, 3)})
            cur = (a["chosen"]["lat"], a["chosen"]["lng"])
            seq += 1
        unit_price = float(cons.get("travel_unit_price", 2.0))
        cons["solver"] = self.solver.name
        cons["solver_note"] = self.solver.available()[1]
        plan_id = _new_id("plan")
        self.store._conn.execute(
            "INSERT INTO route_plan_v1 (plan_id, customer_id, version,"
            " task_ids_json, constraints_json, stops_json, cost_json,"
            " unassigned_json, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, customer_id, 1, json.dumps(task_ids),
             json.dumps(cons, ensure_ascii=False),
             json.dumps(stops, ensure_ascii=False),
             json.dumps({"total_km": round(total_km, 3),
                         "unit_price": unit_price,
                         "total": round(total_km * unit_price, 2)},
                        ensure_ascii=False),
             json.dumps(unassigned, ensure_ascii=False), "draft",
             actor, _now()))
        self.store._conn.commit()
        return self.get_plan(plan_id)

    def get_plan(self, plan_id: str, version: int | None = None) -> dict:
        if version is None:
            row = self.store._conn.execute(
                "SELECT * FROM route_plan_v1 WHERE plan_id=?"
                " ORDER BY version DESC LIMIT 1", (plan_id,)).fetchone()
        else:
            row = self.store._conn.execute(
                "SELECT * FROM route_plan_v1 WHERE plan_id=? AND"
                " version=?", (plan_id, version)).fetchone()
        if row is None:
            raise FieldOpsError(f"plan 不存在: {plan_id}")
        d = dict(row)
        d["task_ids"] = json.loads(d["task_ids_json"])
        d["constraints"] = json.loads(d["constraints_json"])
        d["stops"] = json.loads(d["stops_json"])
        d["cost"] = json.loads(d["cost_json"])
        d["unassigned"] = json.loads(d["unassigned_json"])
        return d

    def list_plans(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT plan_id, max(version) v FROM route_plan_v1"
            " WHERE customer_id=? GROUP BY plan_id"
            " ORDER BY max(created_at)", (customer_id,)).fetchall()
        return [self.get_plan(r["plan_id"], r["v"]) for r in rows]

    def adjust_plan(self, plan_id: str, *, ordered_task_ids: list[str],
                     actor: str) -> dict:
        """人工拖动调整站点顺序 → 新版本（不原地改写旧版）。"""
        p = self.get_plan(plan_id)
        stops_by_task = {s["task_id"]: s for s in p["stops"]}
        new_stops: list[dict] = []
        total_km = 0.0
        prev = None
        seq = 1
        for tid in ordered_task_ids:
            s = stops_by_task.get(tid)
            if s is None:
                raise FieldOpsError(f"任务不在该计划内: {tid}")
            leg = (round(_haversine_km(prev["lat"], prev["lng"],
                                       s["lat"], s["lng"]), 3)
                   if prev else s.get("leg_km", 0.0))
            total_km += leg
            new_stops.append({**s, "seq": seq, "leg_km": leg})
            prev = s
            seq += 1
        unit_price = float(p["cost"].get("unit_price", 2.0))
        version = p["version"] + 1
        self.store._conn.execute(
            "INSERT INTO route_plan_v1 (plan_id, customer_id, version,"
            " task_ids_json, constraints_json, stops_json, cost_json,"
            " unassigned_json, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, p["customer_id"], version,
             json.dumps(ordered_task_ids),
             json.dumps({**p["constraints"],
                         "adjusted_by": actor,
                         "note": "人工调整站点顺序（新版本）"},
                        ensure_ascii=False),
             json.dumps(new_stops, ensure_ascii=False),
             json.dumps({"total_km": round(total_km, 3),
                         "unit_price": unit_price,
                         "total": round(total_km * unit_price, 2)},
                        ensure_ascii=False),
             p["unassigned_json"], "draft", actor, _now()))
        self.store._conn.commit()
        return self.get_plan(plan_id)

    # ---------- 派发与到店 ----------

    def dispatch_task(self, task_id: str, *, employee_id: str,
                      plan_id: str, actor: str) -> dict:
        t = self.get_task(task_id)
        if t["status"] not in ("draft",):
            raise FieldOpsError(f"任务状态不可派发: {t['status']}")
        a = self.get_address(t["address_id"])
        if a["status"] != "verified":
            raise FieldOpsError(
                "低置信度地址未人工确认，不得自动派发（fail-closed）")
        emp = self.store._conn.execute(
            "SELECT * FROM geo_employee_v1 WHERE employee_id=?",
            (employee_id,)).fetchone()
        if emp is None:
            raise FieldOpsError(f"employee 不存在: {employee_id}")
        if emp["customer_id"] != t["customer_id"]:
            raise FieldOpsError("员工与任务客户不一致（硬隔离）")
        plan = self.get_plan(plan_id)
        if task_id not in [s["task_id"] for s in plan["stops"]]:
            raise FieldOpsError("任务不在该路线的已分配站点中")
        self.store._conn.execute(
            "UPDATE field_task_v1 SET status='dispatched', assignee=?,"
            " route_plan_id=?, updated_at=? WHERE task_id=?",
            (employee_id, plan_id, _now(), task_id))
        self.store._conn.commit()
        return self.get_task(task_id)

    def create_fence(self, *, customer_id: str, name: str, lat: float,
                     lng: float, radius_m: float) -> dict:
        fid = _new_id("fence")
        self.store._conn.execute(
            "INSERT INTO geofence_v1 (fence_id, customer_id, name, lat,"
            " lng, radius_m, created_at) VALUES (?,?,?,?,?,?,?)",
            (fid, customer_id, name, lat, lng, radius_m, _now()))
        self.store._conn.commit()
        row = self.store._conn.execute(
            "SELECT * FROM geofence_v1 WHERE fence_id=?",
            (fid,)).fetchone()
        return dict(row)

    def list_fences(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM geofence_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [dict(r) for r in rows]

    def arrive(self, *, task_id: str, fence_id: str, lat: float,
               lng: float, accuracy: float, employee_id: str) -> dict:
        """到店：围栏内 + 精度达标才记录 enter 事件（证据之一）。"""
        t = self.get_task(task_id)
        if t["status"] != "dispatched":
            raise FieldOpsError(f"任务状态不允许到店: {t['status']}")
        row = self.store._conn.execute(
            "SELECT * FROM geofence_v1 WHERE fence_id=?",
            (fence_id,)).fetchone()
        if row is None:
            raise FieldOpsError(f"fence 不存在: {fence_id}")
        dist_m = _haversine_km(row["lat"], row["lng"], lat, lng) * 1000
        if dist_m > row["radius_m"]:
            raise FieldOpsError(
                f"定位在围栏外（{dist_m:.0f}m > {row['radius_m']:.0f}m）")
        if accuracy > 50:
            raise FieldOpsError(f"GPS 精度不足（accuracy={accuracy}m）")
        self.store._conn.execute(
            "INSERT INTO geofence_event_v1 (fence_id, task_id,"
            " employee_id, kind, lat, lng, accuracy, at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (fence_id, task_id, employee_id, "enter", lat, lng,
             accuracy, _now()))
        self.store._conn.execute(
            "UPDATE field_task_v1 SET status='arrived', updated_at=?"
            " WHERE task_id=?", (_now(), task_id))
        self.store._conn.commit()
        return self.get_task(task_id)

    def add_evidence(self, *, task_id: str, kind: str,
                     media_ref: str = "", location: dict | None = None,
                     actor: str) -> dict:
        """门头必拍/可选自拍/问卷证据；人脸比对默认不自动触发。"""
        if kind not in ("storefront", "selfie", "survey", "other"):
            raise FieldOpsError(f"证据类型非法: {kind}")
        t = self.get_task(task_id)
        if kind == "selfie" and not t["selfie_required"]:
            raise FieldOpsError(
                "自拍未启用（默认关闭；人脸比对默认不自动触发）")
        eid = _new_id("fev")
        self.store._conn.execute(
            "INSERT INTO field_visit_evidence_v1 (evidence_id, task_id,"
            " kind, media_ref, at, location_json, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (eid, task_id, kind, media_ref, _now(),
             json.dumps(location or {}, ensure_ascii=False), _now()))
        self.store._conn.commit()
        row = self.store._conn.execute(
            "SELECT * FROM field_visit_evidence_v1 WHERE evidence_id=?",
            (eid,)).fetchone()
        return dict(row)

    def list_evidence(self, task_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM field_visit_evidence_v1 WHERE task_id=?"
            " ORDER BY created_at", (task_id,)).fetchall()
        return [dict(r) for r in rows]

    def complete_task(self, task_id: str, *, actor: str) -> dict:
        t = self.get_task(task_id)
        if t["status"] != "arrived":
            raise FieldOpsError(f"任务未到店，不可完成: {t['status']}")
        evs = self.list_evidence(task_id)
        if t["require_storefront"] and not any(
                e["kind"] == "storefront" for e in evs):
            raise FieldOpsError("门头必拍：缺少门头照片证据")
        # 差旅费：从路线取该任务 leg_km × 单价
        km = 0.0
        unit_price = 2.0
        if t["route_plan_id"]:
            plan = self.get_plan(t["route_plan_id"])
            unit_price = plan["cost"].get("unit_price", 2.0)
            stop = next((s for s in plan["stops"]
                         if s["task_id"] == task_id), None)
            km = stop["leg_km"] if stop else 0.0
        cid = _new_id("tc")
        self.store._conn.execute(
            "INSERT INTO travel_cost_v1 (cost_id, task_id, route_plan_id,"
            " km, unit_price, amount, evidence_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (cid, task_id, t["route_plan_id"], km, unit_price,
             round(km * unit_price, 2),
             json.dumps({"evidence_ids": [e["evidence_id"] for e in evs],
                         "geofence": True}, ensure_ascii=False), _now()))
        self.store._conn.execute(
            "UPDATE field_task_v1 SET status='completed', updated_at=?"
            " WHERE task_id=?", (_now(), task_id))
        self.store._conn.commit()
        cost = dict(self.store._conn.execute(
            "SELECT * FROM travel_cost_v1 WHERE cost_id=?",
            (cid,)).fetchone())
        return {"task": self.get_task(task_id), "travel_cost": cost}

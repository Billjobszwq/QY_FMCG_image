// ABOSV3 T7：地图面板（MapLibre 开源地图 + 可配置瓦片源；无瓦片时
// 诚实降级为本地散点图，其他模块不受影响）。
// 图层：地址点位（按状态着色）、围栏圆、路线折线与站点、未分配任务。
import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { iamGet } from "../api";
import { ErrorState, Loading } from "../platform/components";

interface MapData {
  points: Array<{ id: string; raw: string; status: string;
    lat: number | null; lng: number | null }>;
  fences: Array<{ fence_id: string; name: string; lat: number;
    lng: number; radius_m: number }>;
  unassigned_tasks: string[];
  plans: Array<{ plan_id: string; version: number; status: string;
    stops: Array<{ seq: number; lat: number; lng: number;
      task_id: string }>; cost: any; solver?: string }>;
  map: { available: boolean; tiles_url: string; reason: string };
}

const STATUS_COLOR: Record<string, string> = {
  pending: "#d97706", verified: "#16a34a", confirmed: "#2563eb",
};

export function GeoMapPanel({ customerId }: { customerId: string }) {
  const [data, setData] = useState<MapData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const holder = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!customerId) return;
    iamGet(`geo/map-data?customer_id=${encodeURIComponent(customerId)}`)
      .then(setData).catch(
        (e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [customerId]);

  const coords = (data?.points ?? []).filter(
    (p) => p.lat !== null && p.lng !== null);

  useEffect(() => {
    if (!data || !holder.current) return;
    if (!data.map.available || !data.map.tiles_url) return; // 降级模式
    if (coords.length === 0) return;
    const center: [number, number] = [
      coords.reduce((s, p) => s + (p.lng ?? 0), 0) / coords.length,
      coords.reduce((s, p) => s + (p.lat ?? 0), 0) / coords.length];
    const map = new maplibregl.Map({
      container: holder.current,
      style: {
        version: 8,
        sources: {
          tiles: { type: "raster",
            tiles: [data.map.tiles_url], tileSize: 256 },
        },
        layers: [{ id: "tiles", type: "raster", source: "tiles" }],
      },
      center, zoom: 10,
    });
    mapRef.current = map;
    map.on("load", () => {
      for (const p of coords) {
        const el = document.createElement("div");
        el.style.width = "12px"; el.style.height = "12px";
        el.style.borderRadius = "50%";
        el.style.background = STATUS_COLOR[p.status] ?? "#666";
        el.style.border = "2px solid #fff";
        el.title = `${p.raw}（${p.status}）`;
        new maplibregl.Marker({ element: el })
          .setLngLat([p.lng!, p.lat!]).addTo(map);
      }
      for (const f of data.fences) {
        const el = document.createElement("div");
        el.style.width = "10px"; el.style.height = "10px";
        el.style.borderRadius = "50%";
        el.style.background = "#7c3aed"; el.title = `围栏 ${f.name}`;
        new maplibregl.Marker({ element: el })
          .setLngLat([f.lng, f.lat]).addTo(map);
      }
      for (const plan of data.plans) {
        if (plan.stops.length < 1) continue;
        const line = plan.stops.map((s) => [s.lng, s.lat]);
        map.addSource(`route-${plan.plan_id}`, {
          type: "geojson",
          data: { type: "Feature", properties: {},
            geometry: { type: "LineString", coordinates: line } },
        });
        map.addLayer({ id: `route-${plan.plan_id}`, type: "line",
          source: `route-${plan.plan_id}`,
          paint: { "line-color": "#dc2626", "line-width": 3 } });
      }
    });
    return () => { map.remove(); mapRef.current = null; };
  }, [data]);

  if (err) return <ErrorState message={err}
    onRetry={() => setErr(null)} />;
  if (!data) return <Loading text="加载地图数据…" />;

  // 降级模式：无瓦片 → 本地 SVG 散点（诚实标注，不伪装地图）
  if (!data.map.available || coords.length === 0) {
    const pts = coords.length ? coords : [];
    const lats = pts.map((p) => p.lat ?? 0);
    const lngs = pts.map((p) => p.lng ?? 0);
    const minLa = Math.min(...lats, 31), maxLa = Math.max(...lats, 32);
    const minLo = Math.min(...lngs, 121),
      maxLo = Math.max(...lngs, 122);
    const px = (lng: number) => 20 + (lng - minLo) / (
      (maxLo - minLo) || 1) * 560;
    const py = (lat: number) => 300 - (lat - minLa) / (
      (maxLa - minLa) || 1) * 280;
    return (
      <div className="card">
        <div className="banner banner-warn">
          地图瓦片未配置（诚实降级）：{data.map.reason}
          —— 以下为坐标散点示意，其他功能不受影响。</div>
        <svg viewBox="0 0 600 320" style={{ width: "100%",
          background: "var(--surface-2)", borderRadius: 8 }}>
          {data.plans.map((pl) => pl.stops.length > 1 && (
            <polyline key={pl.plan_id}
              points={pl.stops.map(
                (s) => `${px(s.lng)},${py(s.lat)}`).join(" ")}
              fill="none" stroke="#dc2626" strokeWidth={2} />))}
          {pts.map((p) => (
            <g key={p.id}>
              <circle cx={px(p.lng!)} cy={py(p.lat!)} r={6}
                fill={STATUS_COLOR[p.status] ?? "#666"}
                stroke="#fff" strokeWidth={1.5}>
                <title>{p.raw}（{p.status}）</title>
              </circle>
              <text x={px(p.lng!) + 8} y={py(p.lat!) + 4}
                fontSize={10} fill="var(--text-muted)">
                {p.raw.slice(0, 12)}</text>
            </g>))}
          {data.fences.map((f) => (
            <circle key={f.fence_id} cx={px(f.lng)} cy={py(f.lat)}
              r={10} fill="none" stroke="#7c3aed"
              strokeDasharray="3 2" strokeWidth={2}>
              <title>围栏 {f.name}（{f.radius_m}m）</title>
            </circle>))}
        </svg>
        <p className="v">未分配任务：
          {data.unassigned_tasks.length} 个</p>
      </div>);
  }

  return (
    <div className="card">
      <div ref={holder} style={{ height: 340, borderRadius: 8,
        overflow: "hidden" }} />
      <p className="v" style={{ marginTop: 6 }}>
        图例：<span style={{ color: "#d97706" }}>●</span> 待确认
        {" "}<span style={{ color: "#16a34a" }}>●</span> 已确认
        {" "}<span style={{ color: "#7c3aed" }}>●</span> 围栏
        {" "}<span style={{ color: "#dc2626" }}>—</span> 路线 ·
        未分配任务 {data.unassigned_tasks.length} 个
        {data.plans.map((p) => ` · ${p.plan_id}(v${p.version
          }) ${p.cost?.total_km ?? 0}km solver=${p.solver ?? "?"}`)}
      </p>
    </div>);
}

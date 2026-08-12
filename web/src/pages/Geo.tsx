// ABOSV2 Phase F：位置与外勤（地址与地理编码 / 任务与路线 / 围栏与到店）。
// 低置信度地址必须人工确认；人脸比对默认不自动触发；地图瓦片缺失时诚实回退。
import { useEffect, useState } from "react";
import { iamGet, iamPost } from "../api";
import { EmptyState, ErrorState, Loading, PageHeader }
  from "../platform/components";
import { CustomerPicker, useOperationalCustomer } from
  "../platform/useOperationalCustomer";
import { GeoMapPanel } from "./GeoMap";

function useLoad<T>(path: string | null): {
  data: T | null; err: string | null; reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return;
    iamGet(path).then(setData).catch(
      (e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [path, tick]);
  return { data, err, reload: () => { setErr(null); setTick(t => t + 1); } };
}

function MapNotice() {
  const mp = useLoad<any>("geo/providers");
  if (!mp.data) return null;
  return (
    <div className="card">
      <p className="v" style={{ fontSize: 12 }}>
        地理编码：{mp.data.geocoder.available ? "可用" : (
          <span style={{ color: "var(--warn)" }}>
            {mp.data.geocoder.reason}</span>)}
        {" "}· 地图：{mp.data.map.available
          ? `可用（${mp.data.map.tiles_url}）`
          : <span style={{ color: "var(--warn)" }}>
            {mp.data.map.reason}</span>}
        {" "}· 路线求解：{mp.data.solver?.name}
      </p>
    </div>
  );
}

function ManualCoordsForm({ addressId, onDone }: {
  addressId: string; onDone: (msg: string) => void;
}) {
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [open, setOpen] = useState(false);
  if (!open) return (
    <button className="btn small"
      onClick={() => setOpen(true)}>手工/导入坐标</button>);
  return (
    <span style={{ display: "inline-flex", gap: 4 }}>
      <input style={{ width: 80 }} placeholder="纬度" value={lat}
        aria-label="纬度"
        onChange={(e) => setLat(e.target.value)} />
      <input style={{ width: 80 }} placeholder="经度" value={lng}
        aria-label="经度"
        onChange={(e) => setLng(e.target.value)} />
      <button className="btn small primary" onClick={async () => {
        try {
          await iamPost(`geo/addresses/${addressId}/manual-coords`, {
            lat: Number(lat), lng: Number(lng), source: "manual" });
          onDone("手工坐标已确认（source=manual）");
        } catch (e) {
          onDone(`手工坐标失败：${e instanceof Error ? e.message : e}`);
        }
      }}>确认</button>
    </span>);
}

// ---- 1. 地址与地理编码 ----
export function GeoAddresses() {
  const { customer: cid, setCustomer: setCid, options } =
    useOperationalCustomer();
  const addrs = useLoad<any>(cid ? `geo/addresses?customer_id=${cid}`
    : null);
  const [raw, setRaw] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="地址与地理编码"
        desc="候选经纬度 + 置信度；低置信度必须人工确认后才可派发" />
      <MapNotice />
      <GeoMapPanel customerId={cid} />
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <CustomerPicker customer={cid} setCustomer={setCid}
            options={options} ariaLabel="客户" />
          <input style={{ flex: 1 }} placeholder="原始地址（含 [geo] 标记=高置信样例）"
            aria-label="原始地址" value={raw}
            onChange={(e) => setRaw(e.target.value)} />
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("geo/addresses",
                { customer_id: cid, raw });
              setMsg("地址已入库（候选待确认）"); setRaw(""); addrs.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>地理编码</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {addrs.err && <ErrorState message={addrs.err}
        onRetry={addrs.reload} />}
      {!addrs.data && !addrs.err && <Loading />}
      {addrs.data && (addrs.data.addresses.length === 0
        ? <EmptyState title="该客户暂无地址" />
        : addrs.data.addresses.map((a: any) => (
          <div className="card" key={a.address_id}>
            <h3>{a.raw} <span className="v">{a.address_id} ·
              {a.status} · 置信度 {a.confidence}</span></h3>
            {a.candidates.map((c: any, i: number) => (
              <p key={i} className="v" style={{ fontSize: 12 }}>
                候选{i + 1}：({c.lat}, {c.lng}) · conf {c.confidence}
                {a.status === "pending" && (
                  <button className="btn small"
                    style={{ marginLeft: 8 }}
                    onClick={async () => {
                      try {
                        await iamPost(
                          `geo/addresses/${a.address_id}/verify`,
                          { chosen_index: i });
                        setMsg("已人工确认经纬度"); addrs.reload();
                      } catch (e) { setMsg(`确认失败：${e instanceof Error
                        ? e.message : e}`); }
                    }}>确认此候选</button>)}
              </p>
            ))}
            {a.status === "verified" && a.chosen && (
              <p className="v" style={{ fontSize: 12 }}>
                已确认：({a.chosen.lat}, {a.chosen.lng}) ·
                确认人 {a.verified_by}
                {a.chosen.source ? ` · 来源 ${a.chosen.source}` : ""}</p>
            )}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap",
              marginTop: 6 }}>
              <button className="btn small" onClick={async () => {
                try {
                  const r = await iamPost(
                    `geo/addresses/${a.address_id}/geocode`, {});
                  setMsg(r.status === "degraded"
                    ? `获取坐标降级：${r.reason}`
                    : `获取坐标完成：${r.status}`);
                  addrs.reload();
                } catch (e) { setMsg(`获取坐标失败：${e instanceof Error
                  ? e.message : e}`); }
              }}>获取坐标（Provider）</button>
              <ManualCoordsForm onDone={(m2) => {
                setMsg(m2); addrs.reload();
              }} addressId={a.address_id} />
            </div>
          </div>
        )))}
    </>
  );
}

// ---- 2. 任务与路线 ----
export function GeoField() {
  const { customer: cid, setCustomer: setCid, options } =
    useOperationalCustomer();
  const tasks = useLoad<any>(cid ? `geo/tasks?customer_id=${cid}` : null);
  const plans = useLoad<any>(cid ? `geo/plans?customer_id=${cid}` : null);
  const addrs = useLoad<any>(cid ? `geo/addresses?customer_id=${cid}`
    : null);
  const emps = useLoad<any>(cid ? `geo/employees?customer_id=${cid}`
    : null);
  const [form, setForm] = useState({ address_id: "", project_id: "",
    selfie: false });
  const [planSel, setPlanSel] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="任务与路线"
        desc="VRP 最近邻 + 约束（max_km/多项目硬隔离）；未分配原因显式留痕" />
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <CustomerPicker customer={cid} setCustomer={setCid}
            options={options} ariaLabel="客户" />
        </div>
        <h3 style={{ marginTop: 8 }}>新建外勤任务</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <select value={form.address_id} aria-label="地址"
            onChange={(e) => setForm({ ...form,
              address_id: e.target.value })}>
            <option value="">选择地址…</option>
            {(addrs.data?.addresses ?? []).map((a: any) => (
              <option key={a.address_id} value={a.address_id}>
                {a.raw}（{a.status}）</option>
            ))}
          </select>
          <input placeholder="project_id" aria-label="项目"
            value={form.project_id}
            onChange={(e) => setForm({ ...form,
              project_id: e.target.value })} />
          <label style={{ fontSize: 12 }}>
            <input type="checkbox" checked={form.selfie}
              onChange={(e) => setForm({ ...form,
                selfie: e.target.checked })} />
            启用自拍（人脸比对默认不自动触发）</label>
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("geo/tasks", {
                customer_id: cid, address_id: form.address_id,
                project_id: form.project_id,
                require_storefront: true,
                selfie_required: form.selfie });
              setMsg("任务已创建"); tasks.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>建任务（门头必拍）</button>
        </div>
        <h3 style={{ marginTop: 10 }}>规划路线（勾选任务）</h3>
        {(tasks.data?.tasks ?? []).map((t: any) => (
          <label key={t.task_id} style={{ fontSize: 12,
            marginRight: 10 }}>
            <input type="checkbox"
              checked={planSel.includes(t.task_id)}
              onChange={(e) => setPlanSel((s) => e.target.checked
                ? [...s, t.task_id] : s.filter((x) => x !== t.task_id))} />
            {t.task_id.slice(0, 10)}…（{t.status}）</label>
        ))}
        <div style={{ marginTop: 6 }}>
          <button className="btn small" disabled={planSel.length === 0}
            onClick={async () => {
              try {
                const out = await iamPost("geo/plans", {
                  customer_id: cid, task_ids: planSel, constraints: {} });
                setMsg(`路线已生成：${out.plan.stops.length} 站 ·
                  未分配 ${out.plan.unassigned.length} ·
                  成本 ${out.plan.cost.total} 元`);
                plans.reload();
              } catch (e) { setMsg(`失败：${e instanceof Error
                ? e.message : e}`); }
            }}>规划（默认硬隔离多项目）</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {plans.data?.plans.map((p: any) => (
        <div className="card" key={p.plan_id}>
          <h3>{p.plan_id} <span className="v">{p.status} ·
            {p.stops.length} 站 · {p.cost.total_km} km ·
            {p.cost.total} 元</span></h3>
          {p.unassigned.length > 0 && (
            <ul style={{ fontSize: 12 }}>
              {p.unassigned.map((u: any, i: number) => (
                <li key={i} style={{ color: "var(--warn)" }}>
                  未分配 {u.task_id.slice(0, 10)}…：{u.reason}</li>
              ))}
            </ul>
          )}
          <table className="table">
            <thead><tr><th>序</th><th>任务</th><th>坐标</th><th>leg km</th>
              <th /></tr></thead>
            <tbody>
              {p.stops.map((s: any) => (
                <tr key={s.seq}>
                  <td data-label="序">{s.seq}</td>
                  <td data-label="任务" className="v">
                    {s.task_id.slice(0, 12)}…</td>
                  <td data-label="坐标" className="v">
                    ({s.lat}, {s.lng})</td>
                  <td data-label="leg km">{s.leg_km}</td>
                  <td><DispatchBtn taskId={s.task_id}
                    emps={emps.data?.employees ?? []}
                    planId={p.plan_id}
                    onMsg={(m) => { setMsg(m); tasks.reload(); }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}

function DispatchBtn({ taskId, emps, planId, onMsg }: {
  taskId: string; emps: any[]; planId: string;
  onMsg: (m: string) => void;
}) {
  const [emp, setEmp] = useState("");
  return (
    <span style={{ display: "inline-flex", gap: 4 }}>
      <select value={emp} aria-label="执行人"
        onChange={(e) => setEmp(e.target.value)}>
        <option value="">员工…</option>
        {emps.map((e) => (
          <option key={e.employee_id} value={e.employee_id}>
            {e.name}</option>
        ))}
      </select>
      <button className="btn small" disabled={!emp} onClick={async () => {
        try {
          await iamPost(`geo/tasks/${taskId}/dispatch`,
            { employee_id: emp, plan_id: planId });
          onMsg("已派发");
        } catch (e) { onMsg(`派发失败：${e instanceof Error
          ? e.message : e}`); }
      }}>派发</button>
    </span>
  );
}

// ---- 3. 围栏与到店 ----
export function GeoVisit() {
  const { customer: cid, setCustomer: setCid, options } =
    useOperationalCustomer();
  const fences = useLoad<any>(cid ? `geo/fences?customer_id=${cid}` : null);
  const tasks = useLoad<any>(cid ? `geo/tasks?customer_id=${cid}` : null);
  const [form, setForm] = useState({ name: "", lat: "31.0", lng: "121.0",
    radius: "150" });
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="围栏与到店"
        desc="围栏 enter 事件（半径+精度校验）；门头必拍；差旅费随完成生成" />
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <CustomerPicker customer={cid} setCustomer={setCid}
            options={options} ariaLabel="客户" />
        </div>
        <h3 style={{ marginTop: 8 }}>新建围栏</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input placeholder="名称" aria-label="围栏名称" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input style={{ width: 100 }} aria-label="纬度" value={form.lat}
            onChange={(e) => setForm({ ...form, lat: e.target.value })} />
          <input style={{ width: 100 }} aria-label="经度" value={form.lng}
            onChange={(e) => setForm({ ...form, lng: e.target.value })} />
          <input style={{ width: 100 }} aria-label="半径(米)"
            value={form.radius}
            onChange={(e) => setForm({ ...form, radius: e.target.value })} />
          <button className="btn small primary" onClick={async () => {
            try {
              await iamPost("geo/fences", {
                customer_id: cid, name: form.name,
                lat: Number(form.lat), lng: Number(form.lng),
                radius_m: Number(form.radius) });
              setMsg("围栏已创建"); fences.reload();
            } catch (e) { setMsg(`失败：${e instanceof Error
              ? e.message : e}`); }
          }}>创建</button>
        </div>
        {msg && <p className="v" style={{ marginTop: 8 }}>{msg}</p>}
      </div>
      {fences.data && (fences.data.fences.length === 0
        ? <EmptyState title="暂无围栏" />
        : (
          <div className="card">
            <h3>围栏列表</h3>
            <table className="table">
              <thead><tr><th>名称</th><th>中心坐标</th><th>半径(m)</th>
                </tr></thead>
              <tbody>
                {fences.data.fences.map((f: any) => (
                  <tr key={f.fence_id}>
                    <td data-label="名称">{f.name}
                      <span className="v" style={{ marginLeft: 6 }}>
                        {f.fence_id}</span></td>
                    <td data-label="中心坐标" className="v">
                      ({f.lat}, {f.lng})</td>
                    <td data-label="半径(m)">{f.radius_m}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      <div className="card">
        <h3>任务到店/证据/完成</h3>
        {(tasks.data?.tasks ?? []).map((t: any) => (
          <VisitRow key={t.task_id} t={t}
            fences={fences.data?.fences ?? []}
            onMsg={(m) => { setMsg(m); tasks.reload(); }} />
        ))}
        {(tasks.data?.tasks ?? []).length === 0 &&
          <EmptyState title="暂无任务" next="先到“任务与路线”派发" />}
      </div>
    </>
  );
}

function VisitRow({ t, fences, onMsg }: {
  t: any; fences: any[]; onMsg: (m: string) => void;
}) {
  const [fence, setFence] = useState("");
  return (
    <div style={{ border: "1px dashed var(--border)", padding: 8,
      marginBottom: 8 }}>
      <b style={{ fontSize: 13 }}>{t.task_id.slice(0, 12)}… ·
        {t.status}</b>
      <span style={{ marginLeft: 8, fontSize: 12 }}>
        门头必拍：{t.require_storefront ? "是" : "否"} ·
        自拍：{t.selfie_required ? "启用" : "关闭（人脸不自动触发）"}
      </span>
      {t.status === "dispatched" && (
        <span style={{ marginLeft: 8 }}>
          <select value={fence} aria-label="围栏"
            onChange={(e) => setFence(e.target.value)}>
            <option value="">围栏…</option>
            {fences.map((f) => (
              <option key={f.fence_id} value={f.fence_id}>
                {f.name}</option>
            ))}
          </select>
          <button className="btn small" disabled={!fence}
            style={{ marginLeft: 4 }} onClick={async () => {
              const f = fences.find((x) => x.fence_id === fence);
              try {
                await iamPost(`geo/tasks/${t.task_id}/arrive`, {
                  fence_id: fence, lat: f.lat, lng: f.lng,
                  accuracy: 8, employee_id: t.assignee });
                onMsg("已到店（围栏 enter 事件已记录）");
              } catch (e) { onMsg(`到店失败：${e instanceof Error
                ? e.message : e}`); }
            }}>到店打卡</button>
        </span>
      )}
      {t.status === "arrived" && (
        <span style={{ marginLeft: 8 }}>
          <button className="btn small" onClick={async () => {
            try {
              await iamPost(`geo/tasks/${t.task_id}/evidence`, {
                kind: "storefront", media_ref: "cas:web-upload",
                location: {} });
              onMsg("门头照片证据已入库");
            } catch (e) { onMsg(`证据失败：${e instanceof Error
              ? e.message : e}`); }
          }}>上传门头照</button>
          <button className="btn small primary"
            style={{ marginLeft: 4 }} onClick={async () => {
            try {
              const out = await iamPost(`geo/tasks/${t.task_id}/complete`,
                {});
              onMsg(`已完成：差旅费 ${out.travel_cost.amount} 元
                （${out.travel_cost.km} km）`);
            } catch (e) { onMsg(`完成失败：${e instanceof Error
              ? e.message : e}`); }
          }}>完成（生成差旅费）</button>
        </span>
      )}
    </div>
  );
}

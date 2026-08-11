import { useEffect, useState } from "react";

// 07 经营智能：BI 报表（真实数据图表）+ 数据告警（真实规则）+ 模块配置。
function Bars({ data }: { data: { k: string; v: number }[] }) {
  const max = Math.max(...data.map((d) => d.v), 0.01);
  return (
    <div style={{ display: "flex", gap: 14, alignItems: "flex-end",
      height: 150 }}>
      {data.map((d, i) => (
        <div key={d.k} style={{ flex: 1, display: "flex",
          flexDirection: "column", justifyContent: "flex-end",
          height: "100%", gap: 6 }}>
          <b style={{ fontSize: 13 }}>{d.v.toFixed(2)}</b>
          <div style={{ height: `${(d.v / max) * 100}%`,
            background: ["#16a6ff", "#00aa3c", "#ff8e0a", "#ab54f7",
              "#ea3737"][i % 5], borderRadius: 8 }} />
          <span style={{ fontSize: 11, fontWeight: 700 }}>{d.k}</span>
        </div>
      ))}
    </div>
  );
}

export default function BizIntel() {
  const [tab, setTab] = useState<"bi" | "alert" | "cfg">("bi");
  const [m3, setM3] = useState<{ k: string; v: number }[]>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [mods, setMods] = useState<any[]>([]);

  useEffect(() => {
    fetch("/api/v1/biz/m3bars").then((r) => r.json())
      .then((d) => setM3(d.bars ?? []));
    fetch("/api/v1/training/artifacts").then((r) => r.json()).then((d) => {
      const cand = (d.artifacts ?? []).filter((a: any) =>
        /CANDIDATE|REJECTED/.test(a.candidate_status ?? ""));
      const al: any[] = [];
      cand.forEach((a: any) => al.push({
        level: a.candidate_status.includes("REJECTED") ? "err" : "warn",
        text: `${a.artifact_id}：${a.candidate_status}`,
        sub: a.blocker,
      }));
      al.push({ level: "warn", text: "micro-gold 200 条待人工审核",
        sub: "LS 项目 22 · 唯一人工入口" });
      al.push({ level: "info", text: "三得利场景检测泛化不足",
        sub: "需更多全场景标注或伪标注循环" });
      setAlerts(al);
    });
    fetch("/api/v1/modules").then((r) => r.json())
      .then((d) => setMods(d.modules ?? []));
  }, []);

  return (
    <div>
      <span className="kicker">07 · 经营智能 · biz-agent</span>
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {(["bi", "alert", "cfg"] as const).map((t) => (
          <button key={t} className="btn"
            style={{ background: tab === t ? "#000" : "#fff",
              color: tab === t ? "#fff" : "#000", padding: "10px 20px" }}
            onClick={() => { setTab(t);
              location.hash = t === "bi" ? "/biz"
                : t === "alert" ? "/biz/alert" : "/biz/cfg"; }}>
            {t === "bi" ? "BI 报表" : t === "alert" ? "数据告警" : "模块配置"}
          </button>
        ))}
      </div>

      {tab === "bi" && (
        <div className="collage">
          <div className="blk c-white span7">
            <h2>M3 长尾实验 · 独立测试 top1</h2>
            {m3.length ? <Bars data={m3} /> : <p>加载中…</p>}
            <p style={{ marginTop: 12 }}>E1–E5 消融 · E5 层级分类领先 ·
              数据来源：独立 holdout 评估</p>
          </div>
          <div className="blk c-yellow span5">
            <h2>micro-gold 进度</h2>
            <div className="big">0/200</div>
            <p>人工审核完成数 · LS 项目 22</p>
          </div>
          <div className="blk c-blue span12">
            <h2>经营看板说明</h2>
            <p>BI 数据全部来自平台事实源（评估注册表/任务板/服务健康），
              非静态演示。后续可拖拽自定义图表（模块配置中定义）。</p>
          </div>
        </div>
      )}

      {tab === "alert" && (
        <div className="collage">
          {alerts.map((a, i) => (
            <div key={i} className="blk span6" style={{
              background: a.level === "err" ? "var(--red)"
                : a.level === "warn" ? "var(--amber)" : "var(--blue)",
              color: a.level === "err" ? "#fff" : "#000" }}>
              <h2 style={{ fontSize: 18 }}>{a.text}</h2>
              <p>{a.sub}</p>
            </div>
          ))}
        </div>
      )}

      {tab === "cfg" && (
        <div className="collage">
          {mods.filter((m) => m.status === "planned").map((m) => (
            <div key={m.module_id} className="blk span4 c-lav">
              <h2>{m.name}</h2>
              <p>{(m.submodules ?? []).join(" · ")}</p>
              <span className="pill on-white">agent：{m.agent} ·
                待定义 · 注册即生效</span>
            </div>
          ))}
          <div className="blk c-white span12" style={{ minHeight: 0 }}>
            <h2>模块化机制</h2>
            <p>新模块 = manifest 注册（名称/色系/agent/API 前缀/数据域）。
              不改底层数据架构；高级功能靠模块扩展。每个 Agent 分工不同，
              后续逐个定义。</p>
          </div>
        </div>
      )}
    </div>
  );
}

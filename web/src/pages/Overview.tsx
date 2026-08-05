import { useEffect, useState } from "react";
import { HealthBody, WorkItemsBody, fetchWorkItems } from "../api";

const KIND_CN: Record<string, string> = {
  human_review: "人工审核",
  training: "训练",
  job: "后台任务",
  labeling: "标注",
  recognition: "识别",
};

// U2-4：阶段→配色（业务语言默认，技术状态进高级详情）
const STAGE_PILL: Record<string, string> = {
  todo: "degraded",
  active: "healthy",
  done: "unavailable",
  blocked: "degraded",
};

export default function Overview({ health }: { health: HealthBody | null }) {
  const [wi, setWi] = useState<WorkItemsBody | null>(null);
  const [wiError, setWiError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = () =>
      fetchWorkItems()
        .then((d) => !stop && setWi(d))
        .catch((e) => !stop && setWiError(e instanceof Error ? e.message : String(e)));
    load();
    const t = setInterval(load, 15000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, []);

  const down = (health?.services ?? []).filter((s) => s.status !== "healthy");
  const s = wi?.summary;

  return (
    <section>
      <h2>我的工作台</h2>

      {wiError && <div className="banner banner-unavailable">任务中心加载失败：{wiError}</div>}
      {s && (
        <>
          <div className="cards">
            <div className="card">
              <div className="k">我的待办</div>
              <div className="v">{s.todos}</div>
            </div>
            <div className="card">
              <div className="k">待人工审核</div>
              <div className="v">{s.pending_review}</div>
            </div>
            <div className="card">
              <div className="k">活动任务</div>
              <div className="v">{s.active}</div>
            </div>
            <div className={`card ${s.blocked.length > 0 ? "card-degraded" : "card-healthy"}`}>
              <div className="k">阻断项</div>
              <div className="v">{s.blocked.length}</div>
            </div>
          </div>

          {s.blocked.length > 0 && (
            <div className="banner banner-degraded">
              <strong>阻断原因：</strong>
              <ul style={{ margin: "6px 0 0" }}>
                {s.blocked.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </div>
          )}

          <h3>下一步建议</h3>
          <ul>
            {s.next_steps.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>

          <h3>任务列表（真实来源聚合，业务语言）</h3>
          {wi && wi.items.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>负责人</th>
                </tr>
              </thead>
              <tbody>
                {wi.items.slice(0, 50).map((w) => (
                  <tr key={w.id}>
                    <td>
                      {w.title}
                      <details className="muted">
                        <summary>高级详情</summary>
                        <pre style={{ fontSize: 11 }}>
                          {JSON.stringify({ raw_status: w.status, ...w.detail }, null, 2)}
                        </pre>
                      </details>
                    </td>
                    <td>{KIND_CN[w.kind] ?? w.kind}</td>
                    <td>
                      <span
                        className={`pill pill-${STAGE_PILL[w.stage] ?? "unavailable"}`}
                        title={w.status}
                      >
                        {w.status_text || w.status}
                      </span>
                    </td>
                    <td>{w.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">暂无任务。</p>
          )}
          {wi && wi.items.length > 50 && (
            <p className="muted">仅显示前 50 条（共 {wi.items.length} 条）。</p>
          )}
        </>
      )}

      <h3>系统状态</h3>
      {!health ? (
        <p className="muted">正在加载系统状态…</p>
      ) : (
        <>
          <div className="cards">
            <div className={`card card-${health.status}`}>
              <div className="k">平台整体状态</div>
              <div className="v">{health.status}</div>
            </div>
            <div className="card">
              <div className="k">受监控服务</div>
              <div className="v">{health.services.length}</div>
            </div>
            <div className="card">
              <div className="k">异常服务</div>
              <div className="v">{down.length}</div>
            </div>
          </div>
          <table>
            <thead>
              <tr>
                <th>服务</th>
                <th>状态</th>
                <th>延迟</th>
                <th>关键</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {health.services.map((sv) => (
                <tr key={sv.name}>
                  <td>{sv.name}</td>
                  <td>
                    <span className={`pill pill-${sv.status}`}>{sv.status}</span>
                  </td>
                  <td>{sv.latency_ms != null ? `${sv.latency_ms} ms` : "—"}</td>
                  <td>{sv.critical ? "是" : "否"}</td>
                  <td className="muted">{sv.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {down.length > 0 && (
            <div className="note">
              系统异常：{down.map((sv) => `${sv.name}（${sv.detail ?? sv.status}）`).join("；")}
            </div>
          )}
          <p className="muted">健康快照时间：{health.generated_at}</p>
        </>
      )}
    </section>
  );
}

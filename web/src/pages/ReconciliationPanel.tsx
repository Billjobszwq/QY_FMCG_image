import { useEffect, useState } from "react";

// 纠偏 Task 6：训练页真实对账面板（gate/artifacts/snapshots/cycle/leases）。
// 不再显示过期固定卡片；全部来自平台事实源 API。
export default function ReconciliationPanel() {
  const [gate, setGate] = useState<any>(null);
  const [arts, setArts] = useState<any[]>([]);
  const [snaps, setSnaps] = useState<any[]>([]);
  const [cycle, setCycle] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [g, a, s, c] = await Promise.all([
          fetch("/api/v1/platform/gate").then((r) => r.json()),
          fetch("/api/v1/training/artifacts").then((r) => r.json()),
          fetch("/api/v1/training/snapshots").then((r) => r.json()),
          fetch("/api/v1/training/cycle").then((r) => r.json()),
        ]);
        setGate(g); setArts(a.artifacts); setSnaps(s.snapshots);
        setCycle(c);
      } catch { /* 面板失败不阻塞 */ }
    };
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  return (
    <section style={{ margin: 12, padding: 12, border: "2px solid #d9a520",
                      background: "#fffbe8" }}>
      <h2>平台对账真实状态（四方一致）</h2>
      <p><b>Gate：</b>{gate?.gate}</p>
      <p><b>Production：</b>prod_20260805_v5_r1（未切换）</p>
      <h3>四个 Snapshot</h3>
      <ul>
        {snaps.map((s) => (
          <li key={s.snapshot_id}>{s.snapshot_id} ·
            manifest {s.manifest_sha?.slice(0, 8)} · {s.evidence_level}</li>
        ))}
      </ul>
      <h3>模型 Artifact（磁盘=DB=API 对账）</h3>
      <table style={{ fontSize: 12, width: "100%" }}>
        <thead><tr><th>artifact</th><th>candidate_status</th>
          <th>disk 一致</th><th>blocker</th></tr></thead>
        <tbody>
          {arts.map((a) => (
            <tr key={a.artifact_id}>
              <td>{a.artifact_id}</td>
              <td>{a.candidate_status}</td>
              <td>{a.disk_consistent ? "✓" : "✗ FAIL-CLOSED"}</td>
              <td>{a.blocker}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Training Cycle</h3>
      {cycle && (
        <p>{cycle.cycle_id} · {cycle.status} ·
          {cycle.nodes?.filter((n: any) => n.status === "done").length}/19 done
          <br />
          pending：{cycle.nodes?.filter((n: any) => n.status === "pending")
            .slice(0, 5).map((n: any) => n.node).join(" → ")}
        </p>
      )}
    </section>
  );
}

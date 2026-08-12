import { useCallback, useEffect, useState } from "react";
import {
  LaneReadiness,
  LegacyModelRow,
  TrainingLanesBody,
  TrainingOverviewBody,
  fetchLegacyModels,
  fetchTrainingLanes,
  fetchTrainingOverview,
  iamGet,
} from "../api";

// GLTC Task 9：NextGen 四训练通道统一控制台。
// 红线：当前生产（production_legacy）与 nextgen 视觉隔离；
// 按钮语义明示（生成计划不耗算力；批准不提交 Job；启动需全绿+授权）。

const LANE_CN: Record<string, string> = {
  detector: "T1 商品定位器（YOLO）",
  classifier: "T2 SKU 分类/表征（ResNet18）",
  segmenter: "T3 SAM 几何精修",
  vlm: "T4 Qwen3-VL 4B QLoRA",
};

const BLOCKER_CN: Record<string, string> = {
  BLOCKED_BY_GOLD: "缺人工金标准",
  BLOCKED_BY_AUTHORIZATION: "未获训练授权",
  BLOCKED_BY_MASK_GOLD: "缺真实 mask 金标准",
  BLOCKED_BY_DATASET: "数据集快照未就绪",
  BLOCKED_BY_HARDWARE_GATE: "Apple G0 未通过",
  BLOCKED_BY_RESOURCE_LEASE: "资源租约冲突",
  BLOCKED_BY_BASE_MODEL: "基础权重校验失败",
  BLOCKED_BY_ENVIRONMENT: "隔离环境缺失",
  CALIBRATION_ONLY: "仅校准模式",
};

export default function TrainingControlPanel() {
  const [lanes, setLanes] = useState<TrainingLanesBody | null>(null);
  const [overview, setOverview] = useState<TrainingOverviewBody | null>(null);
  const [legacy, setLegacy] = useState<LegacyModelRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stdCurrent, setStdCurrent] = useState<any | null>(null);

  useEffect(() => {
    // UATCC T5：平台当前 standard bundle 与诚实状态口径
    iamGet("recognition/standard")
      .then((d) => setStdCurrent(d.current)).catch(() => {});
  }, []);

  const reload = useCallback(async () => {
    try {
      const [l, o, m] = await Promise.all([
        fetchTrainingLanes(),
        fetchTrainingOverview(),
        fetchLegacyModels(),
      ]);
      setLanes(l);
      setOverview(o);
      setLegacy(m.models);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 15000);
    return () => clearInterval(t);
  }, [reload]);

  const laneCard = (lane: string, info: LaneReadiness) => (
    <div
      key={lane}
      className="card"
      style={{
        border: "1px solid var(--border, #ccc)",
        borderRadius: 8,
        padding: 12,
        minWidth: 260,
      }}
    >
      <h3 style={{ marginTop: 0 }}>
        {LANE_CN[lane] ?? lane}{" "}
        <span
          style={{
            color: info.ready ? "#0a7f2e" : "#b3541e",
            fontSize: "0.8em",
          }}
        >
          {info.ready ? "就绪" : "受阻"}
        </span>
      </h3>
      <p className="muted" style={{ margin: "4px 0" }}>
        lineage：{info.lineage_family} · gold 区域：{info.gold_regions}
      </p>
      {info.blockers.length === 0 ? (
        <p style={{ color: "#0a7f2e" }}>无 blocker。</p>
      ) : (
        <ul style={{ paddingLeft: 18, margin: "4px 0" }}>
          {info.blockers.map((b) => (
            <li key={b.code}>
              <strong>{BLOCKER_CN[b.code] ?? b.code}</strong>：{b.detail}
            </li>
          ))}
        </ul>
      )}
      <div className="muted" style={{ fontSize: "0.85em" }}>
        生成计划=不耗算力 · 请求批准=不提交 Job · 启动训练=全 gate
        绿+人工授权后才入队
      </div>
    </div>
  );

  return (
    <section>
      <h2>训练控制台（NextGen 四通道 · fmcg_nextgen_v1）</h2>
      {stdCurrent?.bundle_id === "prod_v4_best_r1" && (
        <p style={{ margin: "6px 0", padding: "6px 10px", borderRadius: 6,
          border: "1px solid #b45309", color: "#b45309",
          fontSize: "0.9em" }}>
          当前本机识别模型：<strong>prod_v4_best_r1</strong>（
          USER_SELECTED_UAT_MODEL）——用户选定的 UAT 模型，尚未完成
          独立人工真值准确率晋级，不写 PRODUCTION_APPROVED；一键回滚
          路径保留（CURRENT.previous.json）。
        </p>)}
      {error && <p style={{ color: "#b00020" }}>加载失败：{error}</p>}

      {lanes && (
        <div
          style={{
            display: "flex",
            gap: 16,
            flexWrap: "wrap",
            alignItems: "stretch",
          }}
        >
          <div
            className="card"
            style={{
              border: "2px solid #3b6ea5",
              borderRadius: 8,
              padding: 12,
              minWidth: 260,
              background: "rgba(59,110,165,0.06)",
            }}
          >
            <h3 style={{ marginTop: 0 }}>当前生产（Legacy）</h3>
            <p style={{ margin: "4px 0" }}>
              <strong>{lanes.production.bundle_id}</strong>
            </p>
            {lanes.production.bundle_id === "prod_v4_best_r1" && (
              <p style={{ margin: "4px 0", fontSize: "0.85em",
                color: "var(--warn, #b45309)" }}>
                当前本机 UAT 模型（USER_SELECTED_UAT_MODEL），尚未完成
                独立准确率晋级；回滚路径保留。
              </p>)}
            <p className="muted" style={{ margin: "4px 0" }}>
              状态：{lanes.production.status} ·{" "}
              {lanes.production.serving ? "serving" : "未服务"}
            </p>
            <p className="muted" style={{ margin: "4px 0" }}>
              {lanes.production.lineage}
            </p>
            <p className="muted" style={{ fontSize: "0.85em" }}>
              仅用于识别与 assisted provisional proposal； 不是 nextgen 的
              parent。
            </p>
          </div>
          {Object.entries(lanes.lanes).map(([lane, info]) =>
            laneCard(lane, info)
          )}
        </div>
      )}
      {lanes && (
        <p className="muted">{lanes.note}</p>
      )}

      {overview && (
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          <div>
            <h3>人工金标准</h3>
            <p>
              可用区域（human_final/gold_verified）：
              <strong>{overview.gold.usable_regions}</strong>
            </p>
            <p className="muted">
              训练授权：{overview.training_authorized ? "已授权" : "未授权"}
            </p>
          </div>
          <div>
            <h3>资源租约（heavy 并发 1 · MPS/MLX 互斥）</h3>
            {overview.leases.length === 0 ? (
              <p className="muted">无活动租约。</p>
            ) : (
              <ul>
                {overview.leases.map((l, i) => (
                  <li key={i}>
                    {l.resource}（{l.mode}）→ {l.run_id}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      <details>
        <summary>旧模型登记账本（只读 · 不移动/不删除）</summary>
        {legacy === null ? (
          <p className="muted">加载中…</p>
        ) : legacy.length === 0 ? (
          <p className="muted">尚未登记。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>model_id</th>
                <th>状态</th>
                <th>路径</th>
                <th>登记时间</th>
              </tr>
            </thead>
            <tbody>
              {legacy.map((m) => (
                <tr key={m.model_id}>
                  <td>{m.model_id}</td>
                  <td>{m.status}</td>
                  <td>{m.path}</td>
                  <td>{m.registered_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
    </section>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ModelRuntimeRow, csrfToken, fetchModelsRuntime } from "../api";

// VLM-016：模型驻留（hot/warm/cold）+ sleeping guardian 诚实状态。

const RESIDENCY_CN: Record<string, string> = {
  hot: "hot（常驻）",
  warm: "warm（按需保活）",
  cold: "cold（按需加载）",
};

const STATE_CN: Record<string, string> = {
  cold: "未加载（冷启动需要时间）",
  loading: "加载到内存中…",
  hot: "在内存中",
  unloading: "卸载中…",
  failed: "加载失败（熔断）",
};

function memoryHint(m: ModelRuntimeRow): string {
  if (m.state === "hot") return "在内存中";
  if (m.state === "loading") return "正在占用内存";
  if (m.state === "failed") return "加载失败，未占用内存";
  return "不在内存中（首次请求需冷启动）";
}

export default function ModelRuntime() {
  const [models, setModels] = useState<ModelRuntimeRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const logged = csrfToken() !== null;

  const reload = useCallback(async () => {
    try {
      const d = await fetchModelsRuntime();
      setModels(d.models);
      setDisabled(false);
      setError(null);
    } catch (e) {
      setModels(null);
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("401")) setError("未登录");
      else if (msg.includes("404")) setDisabled(true);
      else setError(msg);
    }
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 15000);
    return () => clearInterval(t);
  }, [reload]);

  const failed = (models ?? []).filter((m) => m.state === "failed");

  return (
    <section>
      <h2>模型驻留（hot / warm / cold）</h2>
      <p className="muted">
        YOLO/ResNet=hot，SAM/OCR/检索=warm，qwen3-vl:4b=cold（sleeping
        guardian：max_concurrency=1、空闲 TTL 卸载、加载失败熔断）。
        相关页面：<Link to="/cascade">级联任务</Link> ·{" "}
        <Link to="/training">训练门禁</Link>
      </p>
      {disabled && (
        <div className="banner banner-degraded">
          模型驻留 API 未启用：当前进程未注入 cascade
          service（shadow 阶段诚实状态）。
        </div>
      )}
      {!logged && !disabled && (
        <div className="banner banner-degraded">
          需要登录：请在右上角登录后查看模型驻留。
        </div>
      )}
      {error && <div className="banner banner-unavailable">错误：{error}</div>}
      {failed.length > 0 && (
        <div className="banner banner-unavailable">
          错误：{failed.map((m) => m.model_id).join("、")} 加载失败，已熔断；
          级联会自动回落上一阶段或转人工，不会静默接受。
        </div>
      )}

      {models === null && !disabled && !error ? (
        <p className="muted">加载中…</p>
      ) : models === null ? (
        <p className="muted">
          模型驻留列表不可用（{error ?? "models/runtime API 未启用，见上方说明"}）。
        </p>
      ) : models.length === 0 ? (
        <p className="muted">
          暂无注册模型（空注册表是诚实状态）：真实 Qwen
          加载被训练保护门禁阻断（BLOCKED_BY_ACTIVE_TRAINING），
          当前仅允许 mock/parse-only 链路。
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>模型</th>
              <th>驻留档位</th>
              <th>内存状态</th>
              <th>队列（活跃租约/并发上限）</th>
              <th>冷启动配置</th>
              <th>最近使用</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.model_id}>
                <td>{m.model_id}</td>
                <td>{RESIDENCY_CN[m.residency] ?? m.residency}</td>
                <td>
                  <span
                    className={`pill pill-${
                      m.state === "hot"
                        ? "healthy"
                        : m.state === "failed"
                          ? "unavailable"
                          : "degraded"
                    }`}
                  >
                    {STATE_CN[m.state] ?? m.state}
                  </span>
                </td>
                <td>
                  {m.active_leases}/{m.max_concurrency}
                  {memoryHint(m) ? ` · ${memoryHint(m)}` : ""}
                </td>
                <td className="muted">空闲 {m.idle_ttl_s}s 后卸载</td>
                <td className="muted">{m.last_used_at ?? "从未"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        说明：12h/48h 是队列业务 SLA（见级联任务页），不是单次模型推理 timeout；
        当前 YOLO 训练运行时，真实 VLM 加载请求会被资源门禁拒绝。
      </p>
    </section>
  );
}

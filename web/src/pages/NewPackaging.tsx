import { useCallback, useEffect, useState } from "react";
import {
  PackageDecisionRow,
  csrfToken,
  fetchPackageDecisions,
  finalizePackageDecision,
} from "../api";

// VLM-016：新包装裁决。Qwen 只能建候选（candidate）；
// 只有人工可以终结为：同 SKU 新包装（沿用旧名/采用新名）、新 SKU、unknown、rejected。

const STATUS_CN: Record<string, string> = {
  candidate: "候选（待裁决）",
  reviewing: "复核中",
  same_sku_new_package: "同 SKU 新包装",
  new_sku: "新 SKU",
  unknown: "无法判定",
  rejected: "已拒绝",
};

const FINAL = new Set([
  "same_sku_new_package", "new_sku", "unknown", "rejected",
]);

function evidenceOf(d: PackageDecisionRow): Array<Record<string, unknown>> {
  try {
    const v = JSON.parse(d.evidence_json ?? "[]");
    return Array.isArray(v) ? v : [v];
  } catch {
    return [];
  }
}

export default function NewPackaging() {
  const [rows, setRows] = useState<PackageDecisionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [newName, setNewName] = useState("");
  const [newSkuId, setNewSkuId] = useState("");
  const logged = csrfToken() !== null;

  const reload = useCallback(async () => {
    try {
      const d = await fetchPackageDecisions(
        statusFilter ? { status: statusFilter } : undefined,
      );
      setRows(d.decisions);
      setDisabled(false);
      setError(null);
    } catch (e) {
      setRows(null);
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("401")) setError("未登录");
      else if (msg.includes("404")) setDisabled(true);
      else setError(msg);
    }
  }, [statusFilter]);

  useEffect(() => {
    reload();
  }, [reload]);

  const finalize = async (
    d: PackageDecisionRow,
    body: {
      status: string;
      name_choice?: string;
      new_sku_id?: string;
      display_name?: string;
    },
  ) => {
    setBusy(true);
    setError(null);
    try {
      await finalizePackageDecision(d.decision_id, body);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const open = (rows ?? []).filter((d) => !FINAL.has(d.status));
  const closed = (rows ?? []).filter((d) => FINAL.has(d.status));

  return (
    <section>
      <h2>新包装裁决（人工终结，Qwen 仅可提交候选）</h2>
      <p className="muted">
        包装变化不自动写商品主数据。裁决选项：同 SKU 新包装并沿用旧名 /
        同 SKU 新包装并采用新名 / 创建新 SKU / 无法判定（unknown）/ 拒绝。
        历史决定不可删除、不可更新，只能追加 supersede 关系。
      </p>
      {disabled && (
        <div className="banner banner-degraded">
          新包装 API 未启用：当前进程未注入 packaging
          facade（shadow 阶段诚实状态）。
        </div>
      )}
      {!logged && !disabled && (
        <div className="banner banner-degraded">
          需要登录：请在右上角登录后裁决新包装候选。
        </div>
      )}
      {error && <div className="banner banner-unavailable">裁决失败：{error}</div>}

      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "8px 0" }}>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">全部状态</option>
          <option value="candidate">候选（待裁决）</option>
          <option value="reviewing">复核中</option>
          <option value="same_sku_new_package">同 SKU 新包装</option>
          <option value="new_sku">新 SKU</option>
          <option value="unknown">无法判定</option>
          <option value="rejected">已拒绝</option>
        </select>
        <span className="muted">共 {rows?.length ?? 0} 条</span>
      </div>

      {rows === null && !disabled && !error ? (
        <p className="muted">加载中…</p>
      ) : rows === null ? (
        <p className="muted">
          新包装候选列表不可用（{error ?? "packaging API 未启用，见上方说明"}）。
        </p>
      ) : rows.length === 0 ? (
        <p className="muted">暂无新包装候选（空队列是诚实状态）。</p>
      ) : (
        <>
          <h3>待裁决候选（{open.length}）</h3>
          {open.length === 0 ? (
            <p className="muted">无待裁决候选。</p>
          ) : (
            open.map((d) => (
              <div key={d.decision_id} className="card" style={{ marginBottom: 12 }}>
                <p>
                  <b>{d.display_name}</b>{" "}
                  <span className="pill pill-degraded">
                    {STATUS_CN[d.status] ?? d.status}
                  </span>{" "}
                  <span className="muted">
                    提交人：{d.created_by} · {d.created_at}
                  </span>
                </p>
                <p className="muted">
                  SKU：{d.sku_id || "（未知 SKU）"} · 包装版本：
                  {d.package_version_id}
                </p>
                {evidenceOf(d).length > 0 && (
                  <details className="tech-details">
                    <summary>候选证据（模型哈希 / token / risk 等技术字段折叠）</summary>
                    <pre className="tech-pre">
                      {JSON.stringify(evidenceOf(d), null, 2)}
                    </pre>
                  </details>
                )}
                <p style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    disabled={busy || !logged}
                    onClick={() =>
                      finalize(d, {
                        status: "same_sku_new_package",
                        name_choice: "keep_old_name",
                      })
                    }
                  >
                    同 SKU 新包装 · 沿用旧名
                  </button>
                  <input
                    placeholder="新显示名（采用新名时填写）"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    style={{ width: 220 }}
                  />
                  <button
                    disabled={busy || !logged || !newName.trim()}
                    onClick={() =>
                      finalize(d, {
                        status: "same_sku_new_package",
                        name_choice: "adopt_new_name",
                        display_name: newName.trim(),
                      })
                    }
                  >
                    同 SKU 新包装 · 采用新名
                  </button>
                  <input
                    placeholder="new_sku_id（新 SKU 时填写）"
                    value={newSkuId}
                    onChange={(e) => setNewSkuId(e.target.value)}
                    style={{ width: 200 }}
                  />
                  <button
                    disabled={busy || !logged || !newSkuId.trim()}
                    onClick={() =>
                      finalize(d, {
                        status: "new_sku",
                        name_choice: "create_new_sku",
                        new_sku_id: newSkuId.trim(),
                      })
                    }
                  >
                    创建新 SKU
                  </button>
                  <button
                    disabled={busy || !logged}
                    onClick={() => finalize(d, { status: "unknown" })}
                  >
                    无法判定
                  </button>
                  <button
                    disabled={busy || !logged}
                    onClick={() => finalize(d, { status: "rejected" })}
                  >
                    拒绝
                  </button>
                </p>
              </div>
            ))
          )}

          <h3>已终结历史（{closed.length}，不可更新、不可删除）</h3>
          {closed.length === 0 ? (
            <p className="muted">无历史裁决。</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>显示名</th>
                  <th>结论</th>
                  <th>名称选择</th>
                  <th>SKU</th>
                  <th>包装版本</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((d) => (
                  <tr key={d.decision_id}>
                    <td>{d.display_name}</td>
                    <td>
                      <span
                        className={`pill pill-${
                          d.status === "rejected" || d.status === "unknown"
                            ? "unavailable"
                            : "healthy"
                        }`}
                      >
                        {STATUS_CN[d.status] ?? d.status}
                      </span>
                    </td>
                    <td className="muted">
                      {d.name_choice === "keep_old_name"
                        ? "沿用旧名"
                        : d.name_choice === "adopt_new_name"
                          ? "采用新名"
                          : d.name_choice === "create_new_sku"
                            ? "创建新 SKU"
                            : d.name_choice ?? "—"}
                    </td>
                    <td>{d.sku_id || "—"}</td>
                    <td className="muted">{d.package_version_id}</td>
                    <td className="muted">{d.updated_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

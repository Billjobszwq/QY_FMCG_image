// ABOS T4：共享状态组件（loading/empty/error/blocked 均有下一步）。
import { ReactNode } from "react";
import { ModuleView, STATUS_CN } from "./registry";

export function Loading({ text = "加载中…" }: { text?: string }) {
  return <div className="state-view" role="status">{text}</div>;
}

export function EmptyState({ title, next }:
  { title: string; next?: string }) {
  return (
    <div className="state-view">
      <div className="title">{title}</div>
      {next && <div className="next">下一步：{next}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }:
  { message: string; onRetry?: () => void }) {
  return (
    <div className="state-view" role="alert">
      <div className="title" style={{ color: "var(--err)" }}>出错了</div>
      <div>{message}</div>
      {onRetry && (
        <div className="next">
          <button className="btn small" onClick={onRetry}>重试</button>
        </div>
      )}
    </div>
  );
}

export function PageHeader({ title, desc, children }:
  { title: string; desc?: string; children?: ReactNode }) {
  return (
    <div className="page-header">
      <h1>{title}</h1>
      {desc && <span className="desc">{desc}</span>}
      {children}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls = status === "live" ? "ok"
    : status === "beta" ? "info"
    : status === "degraded" ? "warn"
    : status === "disabled" ? "err" : "muted";
  return <span className={`badge ${cls}`}>{STATUS_CN[status] ?? status}</span>;
}

// ABOS T10：planned 模块诚实插槽 —— 说明目标/依赖/可接入 Data Product/
// 下一实施包；不展示假图表、不允许操作。
export function PlannedModule({ module }: { module: ModuleView }) {
  return (
    <div className="card planned-slot">
      <h3>{module.name} <StatusBadge status={module.status} /></h3>
      <p className="goal">
        该模块目前只有规格和插槽（planned），尚无真实后端。
        接入后将使用与识别域相同的契约：Module Manifest、
        Domain Agent、Data Product、权限与计费。
      </p>
      <dl>
        <dt>目标</dt>
        <dd>{module.navigation[0]?.description || module.name}</dd>
        <dt>API 前缀</dt>
        <dd><code>{module.api_prefix || "—"}</code></dd>
        <dt>Data Product</dt>
        <dd>{module.data_products.join("、") || "—"}</dd>
        <dt>权限范围</dt>
        <dd>{module.permission_scopes.join("、") || "—"}</dd>
        <dt>计费单位</dt>
        <dd>{module.billing_units.join("、") || "—"}</dd>
        <dt>依赖</dt>
        <dd>{module.dependencies.join("、") || "无"}</dd>
        <dt>下一实施包</dt>
        <dd>按 Domain Pack 规格实现后端后，将 Manifest 状态改为
          live 并补齐二级功能页。</dd>
      </dl>
      <div className="banner banner-info">
        本页不展示模拟数据。planned 状态来自 Module Registry 实时投影。
      </div>
    </div>
  );
}

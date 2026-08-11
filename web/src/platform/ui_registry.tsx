// ABOSV2 Z-1：ModuleUIRegistry —— 模块路由 → 受控组件的唯一注册表。
// App.tsx 不再逐条手写模块路由；本文件的 MODULE_ROUTES 键必须与后端
// module_catalog 的导航路由严格一致（契约测试双向校验，缺失 fail-closed）。
// 禁止任意远程代码/HTML 注入：仅允许静态导入的本地组件。
import { useEffect, useMemo, useState } from "react";
import type { HealthBody } from "../api";
import { fetchAgents } from "../api";
import type { ModuleView, PlatformIdentity } from "./registry";
import Home from "../pages/Home";
import GraphRuns from "../pages/GraphRuns";
import {
  WorkflowAgentsAndModels, WorkflowApprovals, WorkflowConnectors,
  WorkflowEvidenceUsage, WorkflowRunCenter,
  WorkflowTemplates,
} from "../pages/Workflow";
import WorkflowCanvas from "../pages/WorkflowCanvas";
import SystemStatus from "../pages/SystemStatus";
import {
  IamAccounts, IamAudit, MasterCustomers, MasterProjects, MasterSkus,
} from "../pages/IamMaster";
import { SurveyDesign, SurveyField, SurveyReport } from "../pages/Survey";
import SurveyBuilder from "../pages/SurveyBuilder";
import {
  AnalyticsAnomalies, AnalyticsReports, AnalyticsSemantics,
} from "../pages/Analytics";
import { GeoAddresses, GeoField, GeoVisit } from "../pages/Geo";
import { FinanceContracts, FinanceInvoices } from "../pages/Finance";
import {
  RecognizeNow, VisionAnnotation, VisionDatasets, VisionEvidence,
  VisionModels, VisionTasks,
} from "../pages/Vision";
import ImportCenter from "../pages/ImportCenter";
import AgentCenter from "../pages/AgentCenter";

export interface ModuleRouteContext {
  health: HealthBody | null;
  modules: ModuleView[];
  identity: PlatformIdentity | null;
}

// ---- Agent 矩阵（/workflow/agents 二级组件之一） ----
export function AgentsMatrix({ modules }: { modules: ModuleView[] }) {
  const [agents, setAgents] = useState<any[] | null>(null);
  useEffect(() => {
    fetchAgents().then((d) => setAgents(d.agents as any[])).catch(
      () => setAgents([]));
  }, []);
  const byId = useMemo(() => {
    const m: Record<string, string> = {};
    for (const mod of modules) {
      for (const a of mod.agents) m[a] = mod.name;
    }
    return m;
  }, [modules]);
  return (
    <div>
      <div className="page-header"><h1>Agent 矩阵</h1>
        <span className="desc">AgentManifest 注册、权限范围与所属模块</span>
      </div>
      <div className="card">
        {agents === null ? <p className="muted">加载中…</p> : (
          <table className="table">
            <thead><tr><th>Agent</th><th>域</th><th>风险</th>
              <th>所属模块</th></tr></thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.agent_id}>
                  <td className="k">{a.agent_id}</td>
                  <td>{a.domain}</td>
                  <td>{a.risk_level}</td>
                  <td>{byId[a.agent_id] ?? "平台"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---- reference.echo：非识别模块证明内核通用 ----
export function ReferenceEcho() {
  const [out, setOut] = useState<string | null>(null);
  useEffect(() => {
    fetch("/api/v1/reference/echo?text=hello-from-workbench")
      .then((r) => r.json()).then((d) => setOut(JSON.stringify(d, null, 2)))
      .catch((e) => setOut(String(e)));
  }, []);
  return (
    <div className="page">
      <div className="page-header"><h1>参考模块 Echo</h1>
        <span className="desc">最小非业务 Domain Pack：注册即可发现/调用</span>
      </div>
      <div className="card">
        <h3>GET /api/v1/reference/echo</h3>
        <pre>{out ?? "调用中…"}</pre>
      </div>
    </div>
  );
}

const wide = (el: JSX.Element) =>
  (<div className="page wide">{el}</div>);

// 路由 → 组件工厂（唯一事实源；键与后端导航路由一一对应）
export const MODULE_ROUTES: Record<
  string, (ctx: ModuleRouteContext) => JSX.Element> = {
  "/home": (ctx) => <Home health={ctx.health} modules={ctx.modules}
    identity={ctx.identity} />,
  // 智能识别
  "/vision/recognize": (ctx) => wide(
    <RecognizeNow health={ctx.health} />),
  "/vision/tasks": () => wide(<VisionTasks />),
  "/vision/annotation": (ctx) => wide(
    <VisionAnnotation health={ctx.health} />),
  "/vision/datasets": () => wide(<VisionDatasets />),
  "/vision/models": () => wide(<VisionModels />),
  "/vision/evidence": () => wide(<VisionEvidence />),
  // 数据与资产
  "/data/import": () => wide(<ImportCenter />),
  "/data/assets": () => wide(<VisionDatasets />),
  "/data/quality": () => wide(<VisionEvidence />),
  // 工作流与 Agent
  "/workflow/studio": () => wide(<WorkflowCanvas />),
  "/workflow/templates": () => wide(<WorkflowTemplates />),
  "/workflow/runs": () => wide(
    <><WorkflowRunCenter /><GraphRuns /></>),
  "/workflow/approvals": () => wide(<WorkflowApprovals />),
  "/workflow/connectors": () => wide(<WorkflowConnectors />),
  "/workflow/agents": () => wide(
    <><WorkflowAgentsAndModels />
      <AgentCenter /></>),
  "/workflow/evidence": () => wide(<WorkflowEvidenceUsage />),
  // 账号与权限 / 主数据
  "/iam/accounts": () => wide(<IamAccounts />),
  "/iam/audit": () => wide(<IamAudit />),
  "/master/customers": () => wide(<MasterCustomers />),
  "/master/projects": () => wide(<MasterProjects />),
  "/master/skus": () => wide(<MasterSkus />),
  // 问卷
  "/survey/design": () => wide(
    <><SurveyBuilder /><SurveyDesign /></>),
  "/survey/field": () => wide(<SurveyField />),
  "/survey/report": () => wide(<SurveyReport />),
  // 分析与 BI
  "/analytics/reports": () => wide(<AnalyticsReports />),
  "/analytics/anomalies": () => wide(<AnalyticsAnomalies />),
  "/analytics/semantics": () => wide(<AnalyticsSemantics />),
  // 位置与外勤
  "/geo/addresses": () => wide(<GeoAddresses />),
  "/geo/field": () => wide(<GeoField />),
  "/geo/visit": () => wide(<GeoVisit />),
  // 财务与结算
  "/finance/contracts": () => wide(<FinanceContracts />),
  "/finance/invoices": () => wide(<FinanceInvoices />),
  // 系统与参考
  "/status": (ctx) => <SystemStatus health={ctx.health} />,
  "/reference/echo": () => <ReferenceEcho />,
};

// 一级模块默认重定向（primary_route → 首个二级路由）
export const MODULE_REDIRECTS: Record<string, string> = {
  "/vision": "/vision/recognize",
  "/workflow": "/workflow/studio",
  "/iam": "/iam/accounts",
  "/master": "/master/customers",
  "/survey": "/survey/design",
  "/analytics": "/analytics/reports",
  "/geo": "/geo/addresses",
  "/finance": "/finance/contracts",
};

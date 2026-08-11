// ABOS T3/T5：Module Registry 投影 —— 前端导航不硬编码模块清单。
// 一级/二级导航、色系、状态全部来自后端 ModuleManifestV2 投影。
export interface NavRouteView {
  route: string;
  label: string;
  description: string;
  actions: string[];
}

export interface ModuleView {
  module_id: string;
  name: string;
  version: string;
  domain: string;
  status: "live" | "beta" | "planned" | "degraded" | "disabled";
  declared_status: string;
  theme_token: string;
  primary_route: string;
  navigation: NavRouteView[];
  agents: string[];
  capabilities: string[];
  api_prefix: string;
  data_products: string[];
  permission_scopes: string[];
  feature_flags: string[];
  dependencies: string[];
  billing_units: string[];
  health_checks: string[];
}

export interface PlatformIdentity {
  product_name: string;
  product_name_zh: string;
  definition: string;
  tagline: string;
  short: string;
  environment: string;
  first_domain_pack: string;
}

export interface ProductionInfo {
  bundle_id: string | null;
  previous?: string;
  found: boolean;
}

let _modules: ModuleView[] | null = null;
let _identity: PlatformIdentity | null = null;

export async function fetchModules(): Promise<ModuleView[]> {
  const r = await fetch("/api/v1/modules");
  if (!r.ok) throw new Error(`modules HTTP ${r.status}`);
  const d = await r.json();
  _modules = d.modules as ModuleView[];
  return _modules;
}

export function cachedModules(): ModuleView[] | null {
  return _modules;
}

export async function fetchIdentity(): Promise<PlatformIdentity> {
  const r = await fetch("/api/v1/platform/identity");
  if (!r.ok) throw new Error(`identity HTTP ${r.status}`);
  const d: PlatformIdentity = await r.json();
  _identity = d;
  return d;
}

export function cachedIdentity(): PlatformIdentity | null {
  return _identity;
}

export async function fetchProduction(): Promise<ProductionInfo> {
  const r = await fetch("/api/v1/platform/production");
  if (!r.ok) throw new Error(`production HTTP ${r.status}`);
  return r.json();
}

// 模块色系 → CSS token（tokens.css 中定义；状态色另行独立）
export function accentVar(themeToken: string): string {
  return `var(--accent-${themeToken}, var(--accent-slate))`;
}
export function accentSoftVar(themeToken: string): string {
  return `var(--accent-${themeToken}-soft, var(--accent-slate-soft))`;
}

export const STATUS_CN: Record<string, string> = {
  live: "运行中",
  beta: "Beta",
  planned: "规划中",
  degraded: "降级",
  disabled: "已停用",
};

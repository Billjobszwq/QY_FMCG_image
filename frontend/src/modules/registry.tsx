/* eslint-disable react-refresh/only-export-components --
   注册表文件：导出路由常量而非 UI 组件，不参与 fast refresh 边界。 */
/**
 * 模块注册表（v3 基础层）：导航分组 → 路由 → 页面组件的唯一事实源。
 *
 * —— 路由键与 web 端 MODULE_ROUTES 对齐（后端 module_catalog 导航路由契约）；
 * —— 页面组件一律 React.lazy 路由级懒加载（页面文件由集成同事创建，
 *    本文件不校验文件存在性）；
 * —— 图标优先复用 components/icons 现有 glyphs，缺失的在本文件内以
 *    16 网格 currentColor 内联 SVG 补齐（stroke 随父级文字色，
 *    状态色由顶部菜单栏/桌面图标的 hover/选中态控制，图标自身不硬编码颜色）。
 */
import { lazy } from "react";
import type { ComponentType, LazyExoticComponent, ReactNode } from "react";
import {
  ChartGlyph,
  DocGlyph,
  FolderGlyph,
  HelpGlyph,
  TerminalGlyph,
} from "@/components/icons";

/** 单个导航条目：路由键 + 中文文案 + 图标 + 懒加载页面。 */
export interface ModuleItem {
  route: string;
  label: string;
  icon: ReactNode;
  Page: LazyExoticComponent<ComponentType>;
}

/** 导航分组。 */
export interface ModuleGroup {
  group: string;
  label: string;
  items: ModuleItem[];
  /**
   * 可见性投影（04 §6）：至少命中一个 scope 才渲染该分组。
   * 未定义 = 所有登录用户可见。前端投影只改善体验；所有 API 仍独立鉴权。
   */
  requiredScopes?: string[];
}

/* ============================================================================
   内联小图标（16 网格 / currentColor / 手工感；仅补缺，不替代正式图标库）
   ========================================================================== */

function glyph(children: ReactNode): ReactNode {
  return (
    <svg
      viewBox="0 0 16 16"
      className="h-4 w-4"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.3}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

/** 首页：小屋 + 门 */
const HomeIcon = glyph(
  <>
    <path d="M2.6 7.3 L8 2.7 L13.4 7.3" />
    <path d="M4 6.4 V13.2 H12 V6.4" />
    <path d="M7 13.2 V10.2 H9 V13.2" />
  </>,
);

/** 系统状态：脉搏折线 */
const PulseIcon = glyph(
  <path d="M1.8 8.6 H4.6 L6.2 4.6 L8.5 11.8 L10.1 8.6 H14.2" />,
);

/** 识别：眼睛 */
const EyeIcon = glyph(
  <>
    <path d="M1.9 8 Q8 3.3 14.1 8 Q8 12.7 1.9 8 Z" />
    <circle cx="8" cy="8" r="2" />
  </>,
);

/** 任务清单：三条文本线 + 一枚对勾 */
const ListCheckIcon = glyph(
  <>
    <path d="M2.6 4.4 H9.2 M2.6 8 H9.2 M2.6 11.6 H7.4" />
    <path d="M10.6 10.8 L11.9 12.2 L14 8.6" />
  </>,
);

/** 标注：铅笔 */
const PenIcon = glyph(
  <>
    <path d="M10.7 3.2 L12.8 5.3 L5.6 12.5 L2.9 13.1 L3.5 10.4 Z" />
    <path d="M9.4 4.5 L11.5 6.6" />
  </>,
);

/** 数据集：层叠 */
const LayersIcon = glyph(
  <>
    <path d="M8 2.4 L13.6 5.3 L8 8.2 L2.4 5.3 Z" />
    <path d="M2.4 8.2 L8 11.1 L13.6 8.2" />
    <path d="M2.4 11 L8 13.9 L13.6 11" />
  </>,
);

/** 模型：立方体 */
const CubeIcon = glyph(
  <>
    <path d="M8 2.3 L13.4 5.1 V10.9 L8 13.7 L2.6 10.9 V5.1 Z" />
    <path d="M2.6 5.1 L8 7.9 L13.4 5.1 M8 7.9 V13.7" />
  </>,
);

/** 证据链：印章 + 绶带 */
const SealIcon = glyph(
  <>
    <circle cx="8" cy="6.4" r="3.6" />
    <path d="M6.4 9.6 L5.4 13.6 L8 12.1 L10.6 13.6 L9.6 9.6" />
    <path d="M6.6 6.4 L7.6 7.4 L9.6 5.2" />
  </>,
);

/** 导入：箭头落入托盘 */
const ImportIcon = glyph(
  <>
    <path d="M2.6 9.6 V12.2 Q2.6 13.4 3.8 13.4 H12.2 Q13.4 13.4 13.4 12.2 V9.6" />
    <path d="M8 2.4 V9.2 M5.4 6.6 L8 9.2 L10.6 6.6" />
  </>,
);

/** 质量金标准：盾牌 + 对勾 */
const ShieldCheckIcon = glyph(
  <>
    <path d="M8 2.1 L13 4 V8 Q13 12 8 13.9 Q3 12 3 8 V4 Z" />
    <path d="M5.8 7.9 L7.4 9.5 L10.4 6.1" />
  </>,
);

/** 运行中心：播放三角 */
const PlayIcon = glyph(<path d="M5.3 3.7 L12.5 8 L5.3 12.3 Z" />);

/** 审批：圆章 + 对勾 */
const CheckBadgeIcon = glyph(
  <>
    <circle cx="8" cy="8" r="5.4" />
    <path d="M5.4 8.2 L7.2 10 L10.8 6.2" />
  </>,
);

/** 连接器：插头 */
const PlugIcon = glyph(
  <>
    <path d="M5.6 2.6 V5.4 M10.4 2.6 V5.4" />
    <path d="M4.2 5.4 H11.8 V8.1 Q11.8 10.6 9.6 11.1 V13.4 H6.4 V11.1 Q4.2 10.6 4.2 8.1 Z" />
  </>,
);

/** 账号：单人 */
const PersonIcon = glyph(
  <>
    <circle cx="8" cy="5.2" r="2.6" />
    <path d="M3.4 13.4 Q3.7 9.7 8 9.7 Q12.3 9.7 12.6 13.4" />
  </>,
);

/** 审计：清单 + 放大镜 */
const AuditIcon = glyph(
  <>
    <path d="M2.8 3.6 H10.2 M2.8 7 H10.2 M2.8 10.4 H6.8" />
    <circle cx="10.8" cy="10.8" r="2.3" />
    <path d="M12.5 12.5 L14.1 14.1" />
  </>,
);

/** 主数据·客户：双人 */
const PeopleIcon = glyph(
  <>
    <circle cx="6" cy="5.4" r="2.2" />
    <path d="M2.4 13.2 Q2.7 9.9 6 9.9 Q8.6 9.9 9.3 11.7" />
    <circle cx="11.3" cy="6.2" r="1.8" />
    <path d="M10.4 13.2 Q10.6 10.9 12.4 10.7 Q13.9 10.9 14 13.2" />
  </>,
);

/** 项目：看板三列 */
const KanbanIcon = glyph(
  <>
    <rect x="2.4" y="2.9" width="11.2" height="10.2" rx="1.5" />
    <path d="M5.3 5.4 V10.4 M8 5.4 V8.6 M10.7 5.4 V11.6" />
  </>,
);

/** SKU：吊牌 */
const TagIcon = glyph(
  <>
    <path d="M2.6 7.2 V3.6 Q2.6 2.6 3.6 2.6 H7.2 L13.3 8.7 Q13.9 9.3 13.3 9.9 L10.5 12.7 Q9.9 13.3 9.3 12.7 Z" />
    <circle cx="5.3" cy="5.3" r="0.9" fill="currentColor" stroke="none" />
  </>,
);

/** 异常检测：警告三角 */
const WarnIcon = glyph(
  <>
    <path d="M8 2.9 L13.9 13 H2.1 Z" />
    <path d="M8 6.6 V9.4" />
    <circle cx="8" cy="11.3" r="0.8" fill="currentColor" stroke="none" />
  </>,
);

/** 语义资产：文本线 + 星芒 */
const SemanticsIcon = glyph(
  <>
    <path d="M2.8 4.4 H13 M2.8 8 H9.4 M2.8 11.6 H7" />
    <path d="M11.9 9.2 L12.5 10.9 L14.2 11.5 L12.5 12.1 L11.9 13.8 L11.3 12.1 L9.6 11.5 L11.3 10.9 Z" />
  </>,
);

/** 问卷：写字板 */
const ClipboardIcon = glyph(
  <>
    <rect x="4" y="3.2" width="8" height="10.4" rx="1.4" />
    <path d="M6.4 3.2 V2.2 H9.6 V3.2" />
    <path d="M6.2 7 H9.8 M6.2 9.8 H8.6" />
  </>,
);

/** 位置：图钉 */
const PinIcon = glyph(
  <>
    <path d="M8 13.8 C8 13.8 12.4 9.7 12.4 6.7 Q12.4 2.6 8 2.6 Q3.6 2.6 3.6 6.7 C3.6 9.7 8 13.8 8 13.8 Z" />
    <circle cx="8" cy="6.7" r="1.8" />
  </>,
);

/** 财务：圆形方孔钱 */
const CoinIcon = glyph(
  <>
    <circle cx="8" cy="8" r="5.6" />
    <path d="M6.4 6.4 H9.6 V9.6 H6.4 Z" />
  </>,
);

/** 主管 Agent · 对话：气泡 + 两行文本线 */
const ChatIcon = glyph(
  <>
    <path d="M2.6 4.4 Q2.6 3 4 3 H12 Q13.4 3 13.4 4.4 V9.4 Q13.4 10.8 12 10.8 H7.3 L4.7 13.1 V10.8 H4 Q2.6 10.8 2.6 9.4 Z" />
    <path d="M5.3 5.9 H10.7 M5.3 8.1 H8.9" />
  </>,
);

/** 主管 Agent · 目标拆解：靶心 + 四向刻线 */
const TargetIcon = glyph(
  <>
    <circle cx="8" cy="8" r="4.9" />
    <circle cx="8" cy="8" r="1.9" />
    <path d="M8 1.6 V3.3 M8 12.7 V14.4 M1.6 8 H3.3 M12.7 8 H14.4" />
  </>,
);

/** 主管 Agent 专用 glyph：四角星（监督者 / 一等公民入口） */
const SparkIcon = glyph(
  <path d="M8 2.1 L9.4 6.6 L13.9 8 L9.4 9.4 L8 13.9 L6.6 9.4 L2.1 8 L6.6 6.6 Z" />,
);

/** 主管 Agent 组在菜单栏 / 桌面图标处的专用 glyph（四角星）。 */
export const SUPERVISOR_GLYPH = SparkIcon;

/* ============================================================================
   页面组件（React.lazy；文件由集成同事创建，此处不验证存在性）
   ========================================================================== */

// P1 首页 / 系统
const Home = lazy(() => import("@/pages/core/Home"));
const SystemStatus = lazy(() => import("@/pages/core/SystemStatus"));
const Help = lazy(() => import("@/pages/core/Help"));
// P2 智能识别（前段）
const Recognize = lazy(() => import("@/pages/vision/Recognize"));
const Tasks = lazy(() => import("@/pages/vision/Tasks"));
const Annotation = lazy(() => import("@/pages/vision/Annotation"));
// P3 智能识别（后段）
const Datasets = lazy(() => import("@/pages/vision/Datasets"));
const Evidence = lazy(() => import("@/pages/vision/Evidence"));
// P3.5 统一模型管理（系统级独立模块，M5/G4）
const ModelConnections = lazy(() => import("@/pages/models/Connections"));
const ModelCatalog = lazy(() => import("@/pages/models/Catalog"));
const ModelBindings = lazy(() => import("@/pages/models/Bindings"));
const ModelGovernance = lazy(() => import("@/pages/models/Governance"));
const ModelLocal = lazy(() => import("@/pages/models/LocalModels"));
// P4 数据与资产
const Import = lazy(() => import("@/pages/data/Import"));
const Assets = lazy(() => import("@/pages/data/Assets"));
const Quality = lazy(() => import("@/pages/data/Quality"));
const KnowledgeGovernance = lazy(() => import("@/pages/data/KnowledgeGovernance"));
// P4.5 认知内核 / 研究（TaaS Research RAG V1）
const ResearchWorkbench = lazy(() => import("@/pages/research/Workbench"));
// P5 工作流与 Agent
const Runs = lazy(() => import("@/pages/workflow/Runs"));
const Templates = lazy(() => import("@/pages/workflow/Templates"));
const Agents = lazy(() => import("@/pages/workflow/Agents"));
const Connectors = lazy(() => import("@/pages/workflow/Connectors"));
const Approvals = lazy(() => import("@/pages/workflow/Approvals"));
// P5.5 主管 Agent（v5 一等公民：对话 / 目标拆解 / 命令审批；矩阵复用 workflow/Agents）
const AgentChat = lazy(() => import("@/pages/agent/Chat"));
const AgentGoals = lazy(() => import("@/pages/agent/Goals"));
const AgentCommands = lazy(() => import("@/pages/agent/Commands"));
// P6 账号与主数据
const Accounts = lazy(() => import("@/pages/master/Accounts"));
const Audit = lazy(() => import("@/pages/master/Audit"));
const Customers = lazy(() => import("@/pages/master/Customers"));
const Projects = lazy(() => import("@/pages/master/Projects"));
const Skus = lazy(() => import("@/pages/master/Skus"));
// P7 分析与 BI
const Reports = lazy(() => import("@/pages/analytics/Reports"));
const Anomalies = lazy(() => import("@/pages/analytics/Anomalies"));
const Semantics = lazy(() => import("@/pages/analytics/Semantics"));
// P8 问卷 / 位置 / 财务（三页内部用页签分组）
const Survey = lazy(() => import("@/pages/biz/Survey"));
const Geo = lazy(() => import("@/pages/biz/Geo"));
const Finance = lazy(() => import("@/pages/biz/Finance"));

/* ============================================================================
   常用分组键常量（桌面壳 / 菜单栏跨窗口跳转共用，避免魔法字符串）
   ========================================================================== */

/** 首页/系统组（健康点 → /status 标签；品牌刺猬 → /home 标签）。 */
export const CORE_GROUP = "core";
/** 主管 Agent 组（一等公民：菜单栏快捷入口 / 独立桌面图标）。 */
export const AGENT_GROUP = "agent";
/** 帮助组（菜单栏「帮助」→ /help 标签）。 */
export const HELP_GROUP = "help";

/* ============================================================================
   MODULE_GROUPS：模块导航分组（v5：顺序即桌面图标顺序）
   ========================================================================== */

export const MODULE_GROUPS: ModuleGroup[] = [
  {
    group: "core",
    label: "首页/系统",
    items: [
      { route: "/home", label: "首页", icon: HomeIcon, Page: Home },
      { route: "/status", label: "系统状态", icon: PulseIcon, Page: SystemStatus },
    ],
  },
  {
    group: "agent",
    label: "主管 Agent",
    items: [
      { route: "/agent/chat", label: "对话", icon: ChatIcon, Page: AgentChat },
      { route: "/agent/goals", label: "目标拆解", icon: TargetIcon, Page: AgentGoals },
      { route: "/agent/commands", label: "命令审批", icon: CheckBadgeIcon, Page: AgentCommands },
      { route: "/agent/matrix", label: "Agent 矩阵", icon: <TerminalGlyph />, Page: Agents },
    ],
  },
  {
    group: "vision",
    label: "智能识别",
    items: [
      { route: "/vision/recognize", label: "识别工作台", icon: EyeIcon, Page: Recognize },
      { route: "/vision/tasks", label: "识别任务", icon: ListCheckIcon, Page: Tasks },
      { route: "/vision/annotation", label: "标注协同", icon: PenIcon, Page: Annotation },
      { route: "/vision/datasets", label: "数据集管理", icon: LayersIcon, Page: Datasets },
      { route: "/vision/evidence", label: "证据链", icon: SealIcon, Page: Evidence },
    ],
  },
  {
    group: "models",
    label: "模型管理",
    // 04 §6：至少命中一个 required scope 才渲染；后端独立鉴权不依赖前端隐藏。
    requiredScopes: ["models.config.read", "models.usage.read"],
    items: [
      { route: "/models/connections", label: "连接管理", icon: PlugIcon, Page: ModelConnections },
      { route: "/models/catalog", label: "模型目录", icon: CubeIcon, Page: ModelCatalog },
      { route: "/models/bindings", label: "能力分配", icon: TargetIcon, Page: ModelBindings },
      { route: "/models/governance", label: "运行治理", icon: AuditIcon, Page: ModelGovernance },
      { route: "/models/local", label: "本地模型", icon: LayersIcon, Page: ModelLocal },
    ],
  },
  {
    group: "data",
    label: "数据与资产",
    items: [
      { route: "/data/import", label: "导入中心", icon: ImportIcon, Page: Import },
      { route: "/data/assets", label: "资产台账", icon: <FolderGlyph />, Page: Assets },
      { route: "/data/quality", label: "质量金标准", icon: ShieldCheckIcon, Page: Quality },
      { route: "/data/knowledge", label: "知识治理", icon: <DocGlyph />, Page: KnowledgeGovernance },
    ],
  },
  {
    group: "research",
    label: "研究与认知",
    items: [
      { route: "/research/workbench", label: "研究工作台", icon: <TerminalGlyph />, Page: ResearchWorkbench },
    ],
  },
  {
    group: "workflow",
    label: "工作流与 Agent",
    items: [
      { route: "/workflow/runs", label: "运行中心", icon: PlayIcon, Page: Runs },
      { route: "/workflow/templates", label: "工作流模板", icon: <DocGlyph />, Page: Templates },
      { route: "/workflow/connectors", label: "连接器", icon: PlugIcon, Page: Connectors },
      { route: "/workflow/approvals", label: "审批队列", icon: CheckBadgeIcon, Page: Approvals },
    ],
  },
  {
    group: "iam",
    label: "账号与主数据",
    items: [
      { route: "/iam/accounts", label: "账号与权限", icon: PersonIcon, Page: Accounts },
      { route: "/iam/audit", label: "审计日志", icon: AuditIcon, Page: Audit },
      { route: "/master/customers", label: "客户主数据", icon: PeopleIcon, Page: Customers },
      { route: "/master/projects", label: "项目主数据", icon: KanbanIcon, Page: Projects },
      { route: "/master/skus", label: "SKU 主数据", icon: TagIcon, Page: Skus },
    ],
  },
  {
    group: "survey",
    label: "问卷",
    items: [
      { route: "/survey", label: "问卷中心", icon: ClipboardIcon, Page: Survey },
    ],
  },
  {
    group: "analytics",
    label: "分析与 BI",
    items: [
      { route: "/analytics/reports", label: "分析报告", icon: <ChartGlyph />, Page: Reports },
      { route: "/analytics/anomalies", label: "异常检测", icon: WarnIcon, Page: Anomalies },
      { route: "/analytics/semantics", label: "语义资产", icon: SemanticsIcon, Page: Semantics },
    ],
  },
  {
    group: "geo",
    label: "位置与外勤",
    items: [
      { route: "/geo", label: "位置与外勤", icon: PinIcon, Page: Geo },
    ],
  },
  {
    group: "finance",
    label: "财务与结算",
    items: [
      { route: "/finance", label: "财务与结算", icon: CoinIcon, Page: Finance },
    ],
  },
  {
    group: "help",
    label: "帮助",
    items: [
      { route: "/help", label: "帮助中心", icon: <HelpGlyph />, Page: Help },
    ],
  },
];

/** 全量条目平铺（按分组顺序），供路由解析 / 快捷键等场景取用。 */
export const MODULE_ITEMS: ModuleItem[] = MODULE_GROUPS.flatMap((g) => g.items);

/** 路由 → 条目 快速索引。 */
export const MODULE_BY_ROUTE: Record<string, ModuleItem> = Object.fromEntries(
  MODULE_ITEMS.map((item) => [item.route, item]),
);

/**
 * 兼容路由别名（04 §3.5）：旧 /vision/models 映射到 /models/local。
 * 兼容期结束前不得移除；别名解析只转发，不复制组件状态源。
 */
export const ROUTE_ALIASES: Record<string, string> = {
  "/vision/models": "/models/local",
};

/** 按路由取条目：先查别名，再查正式路由。 */
export function itemForRoute(route: string): ModuleItem | undefined {
  const resolved = ROUTE_ALIASES[route] ?? route;
  return MODULE_BY_ROUTE[resolved];
}

/**
 * 可见分组投影（04 §6）：
 * —— 无 requiredScopes 的分组对所有登录用户可见；
 * —— scopes 为 null/undefined（whoami 未加载或失败）时受限分组
 *    fail-closed 隐藏；
 * —— 命中任一 required scope 即可见（细粒度动作由后端独立鉴权）。
 */
export function visibleGroups(scopes: string[] | null | undefined): ModuleGroup[] {
  return MODULE_GROUPS.filter((g) => {
    if (!g.requiredScopes || g.requiredScopes.length === 0) return true;
    if (!scopes || scopes.length === 0) return false;
    return g.requiredScopes.some((s) => scopes.includes(s));
  });
}

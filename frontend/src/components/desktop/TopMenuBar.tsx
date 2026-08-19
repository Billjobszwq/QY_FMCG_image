/**
 * 顶部菜单栏（v5 交互范式）：只放跨窗口全局真功能，不放导航下拉。
 *
 * 布局（左 → 右）：
 * —— 品牌区：HedgehogMark（点击 = 首页组窗口 + /home 标签）+ 平台名「TaaS」+ version；
 * —— 菜单「窗口」：层叠 / 平铺 / 全部最小化 / 关闭全部（windowStore 四操作）；
 * —— 菜单「帮助」：打开帮助组窗口并激活 /help 标签（requestTab + 开窗）；
 *    Esc 与外部 pointerdown 收起（document 监听）；
 * —— 主管 Agent 快捷按钮（一等公民入口：开窗 / 置前主管组窗口）；
 * —— 右侧：健康点（fetchHealth；点击 = 首页组窗口 + /status 标签）+ me 名称 + 退出。
 *
 * 设计红线：无渐变无毛玻璃；accent 仅 hover/focus/选中态；文本只穿
 * text-primary/secondary（健康色只落在那 6px 圆点上）。
 */
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { AGENT_GROUP, CORE_GROUP, HELP_GROUP, SUPERVISOR_GLYPH } from "@/modules/registry";
import { fetchHealth, fetchVersion } from "@/lib/api";
import type { HealthStatus } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useModuleTabs } from "@/store/moduleTabs";
import { useWindowManager } from "@/store/windowStore";
import { HedgehogMark } from "@/components/icons";
import { Button } from "@/components/ui/button";

/** 健康状态 → 圆点色 + 中文文案（色只落圆点，文字仍为次级色）。 */
const HEALTH_META: Record<HealthStatus, { dot: string; label: string }> = {
  healthy: { dot: "bg-success", label: "正常" },
  degraded: { dot: "bg-warning", label: "降级" },
  unavailable: { dot: "bg-serious", label: "离线" },
};

/** 当前展开的菜单键；null 表示全部收起。 */
type MenuKey = "window" | "help" | null;

export interface TopMenuBarProps {
  /** 打开 / 置前模块分组窗口（窗口 id = "mod:" + groupKey，由桌面壳实现）。 */
  onOpenGroup: (groupKey: string) => void;
}

export function TopMenuBar({ onOpenGroup }: TopMenuBarProps) {
  const me = useAuth((s) => s.me);
  const logout = useAuth((s) => s.logout);
  const [openMenu, setOpenMenu] = useState<MenuKey>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  /** 当前展开菜单的容器（按钮 + 下拉），外部 pointerdown 判定用。 */
  const menuRef = useRef<HTMLDivElement | null>(null);

  /* 版本号：失败静默（不展示）。 */
  useEffect(() => {
    let alive = true;
    fetchVersion()
      .then((d) => {
        if (alive) setVersion(d.version);
      })
      .catch(() => {
        /* 静默失败 */
      });
    return () => {
      alive = false;
    };
  }, []);

  /* 平台健康：网络失败按「离线」呈现。 */
  useEffect(() => {
    let alive = true;
    fetchHealth()
      .then((d) => {
        if (alive) setHealth(d.status);
      })
      .catch(() => {
        if (alive) setHealth("unavailable");
      });
    return () => {
      alive = false;
    };
  }, []);

  /* Esc 与外部 pointerdown 收起下拉（document 监听） */
  useEffect(() => {
    if (!openMenu) return;
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openMenu]);

  /** 请求某分组窗口的标签并开窗 / 置前（跨窗口跳转统一入口）。 */
  const gotoTab = (groupKey: string, route: string) => {
    useModuleTabs.getState().requestTab(groupKey, route);
    onOpenGroup(groupKey);
  };

  /** 「窗口」菜单条目：全部调用 windowStore 的整桌操作。 */
  const windowMenuItems: Array<{ label: string; run: () => void }> = [
    { label: "层叠窗口", run: () => useWindowManager.getState().cascadeWindows() },
    { label: "平铺窗口", run: () => useWindowManager.getState().tileWindows() },
    { label: "全部最小化", run: () => useWindowManager.getState().minimizeAll() },
    { label: "关闭全部", run: () => useWindowManager.getState().closeAllWindows() },
  ];

  const healthMeta = health ? HEALTH_META[health] : null;

  /** 下拉菜单壳：按钮 + 条目列表（两枚菜单共用同一样式）。 */
  const renderMenu = (
    key: Exclude<MenuKey, null>,
    label: string,
    items: Array<{ label: string; run: () => void }>,
  ) => {
    const expanded = openMenu === key;
    return (
      <div
        className="relative shrink-0"
        ref={expanded ? menuRef : undefined}
      >
        <button
          type="button"
          onClick={() => setOpenMenu(expanded ? null : key)}
          aria-expanded={expanded}
          aria-haspopup="menu"
          className={cn(
            "cursor-pointer rounded px-2 py-1 text-[13px] transition-colors duration-200 ease-out outline-none",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
            expanded
              ? "bg-background text-text-primary"
              : "text-text-secondary hover:text-accent",
          )}
        >
          {label}
        </button>
        {expanded && (
          <div
            role="menu"
            className="absolute left-0 top-full z-[6000] min-w-40 rounded-b-md border border-border bg-surface py-1 shadow-window-active"
          >
            {items.map((item) => (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                onClick={() => {
                  item.run();
                  setOpenMenu(null);
                }}
                className={cn(
                  "block w-full cursor-pointer px-2 py-1 text-left text-[13px] text-text-secondary",
                  "transition-colors duration-200 ease-out outline-none",
                  "hover:bg-background/70 hover:text-accent",
                  "focus-visible:bg-background/70 focus-visible:text-accent focus-visible:outline-none",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <header className="relative z-[6000] flex h-[var(--titlebar-height)] shrink-0 items-center gap-1 border-b border-border bg-surface px-2">
      {/* 左：品牌 + 平台名 + 版本 */}
      <div className="flex shrink-0 items-center gap-1.5 pr-2">
        <HedgehogMark label="打开首页" onClick={() => gotoTab(CORE_GROUP, "/home")} />
        <span className="font-display text-[13px] font-bold text-text-primary">
          TaaS
        </span>
        {version && (
          <span className="text-xs text-text-secondary">{version}</span>
        )}
      </div>

      {/* 中左：窗口 / 帮助 菜单 + 主管 Agent 快捷入口 */}
      <nav className="flex min-w-0 flex-1 items-center gap-0.5">
        {renderMenu("window", "窗口", windowMenuItems)}
        {renderMenu("help", "帮助", [
          { label: "帮助中心", run: () => gotoTab(HELP_GROUP, "/help") },
        ])}
        <button
          type="button"
          onClick={() => onOpenGroup(AGENT_GROUP)}
          title="打开主管 Agent 工作台"
          className={cn(
            "ml-1 flex cursor-pointer items-center gap-1.5 rounded px-2 py-1 text-[13px]",
            "transition-colors duration-200 ease-out outline-none",
            "text-text-secondary hover:text-accent",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
          )}
        >
          <span aria-hidden="true" className="shrink-0">
            {SUPERVISOR_GLYPH}
          </span>
          主管 Agent
        </button>
      </nav>

      {/* 右：健康点 + me 名称 + 退出 */}
      <div className="flex shrink-0 items-center gap-2 pl-2">
        {healthMeta && (
          <button
            type="button"
            onClick={() => gotoTab(CORE_GROUP, "/status")}
            title={`平台状态：${healthMeta.label}`}
            className={cn(
              "flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-xs text-text-secondary",
              "transition-colors duration-200 ease-out outline-none",
              "hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
            )}
          >
            <span
              aria-hidden="true"
              className={cn("h-1.5 w-1.5 rounded-full", healthMeta.dot)}
            />
            {healthMeta.label}
          </button>
        )}
        {me && (
          <span className="max-w-28 truncate text-[13px] text-text-primary">
            {me.actor}
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            void logout();
          }}
        >
          退出
        </Button>
      </div>
    </header>
  );
}

export default TopMenuBar;

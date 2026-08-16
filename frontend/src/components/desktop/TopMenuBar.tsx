/**
 * 顶部菜单栏（v4 交互范式，macOS 式），替代旧版侧边栏。
 *
 * 布局（左 → 右）：
 * —— 品牌区：HedgehogMark（点击 = 打开或置前 /home）+ 平台名「TaaS」+ version；
 * —— 中左：MODULE_GROUPS 十组模块菜单；点击展开下拉，条目点击 = 开窗 + 收起；
 *    Esc 与外部 pointerdown 收起（document 监听）；
 * —— 右侧：健康点（fetchHealth，可点击打开 /status）+ me 名称 + 退出。
 *
 * 设计红线：无渐变无毛玻璃；accent 仅 hover/focus/选中态；文本只穿
 * text-primary/secondary（健康色只落在那 6px 圆点上）。
 */
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { MODULE_GROUPS } from "@/modules/registry";
import { fetchHealth, fetchVersion } from "@/lib/api";
import type { HealthStatus } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { HedgehogMark } from "@/components/icons";
import { Button } from "@/components/ui/button";

/** 健康状态 → 圆点色 + 中文文案（色只落圆点，文字仍为次级色）。 */
const HEALTH_META: Record<HealthStatus, { dot: string; label: string }> = {
  healthy: { dot: "bg-success", label: "正常" },
  degraded: { dot: "bg-warning", label: "降级" },
  unavailable: { dot: "bg-serious", label: "离线" },
};

export interface TopMenuBarProps {
  /** 当前已打开窗口对应的路由集合（条目右侧圆点）。 */
  openRoutes: Set<string>;
  /** 打开 / 置前模块窗口（品牌区 /status、健康点、条目共用）。 */
  onOpen: (route: string) => void;
}

export function TopMenuBar({ openRoutes, onOpen }: TopMenuBarProps) {
  const me = useAuth((s) => s.me);
  const logout = useAuth((s) => s.logout);
  /** 当前展开的分组 group 键；null 表示全部收起。 */
  const [openGroup, setOpenGroup] = useState<string | null>(null);
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
    if (!openGroup) return;
    const onPointerDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenGroup(null);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenGroup(null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openGroup]);

  const healthMeta = health ? HEALTH_META[health] : null;

  return (
    <header className="relative z-[6000] flex h-[var(--titlebar-height)] shrink-0 items-center gap-1 border-b border-border bg-surface px-2">
      {/* 左：品牌 + 平台名 + 版本 */}
      <div className="flex shrink-0 items-center gap-1.5 pr-2">
        <HedgehogMark label="打开首页" onClick={() => onOpen("/home")} />
        <span className="font-display text-[13px] font-bold text-text-primary">
          TaaS
        </span>
        {version && (
          <span className="text-xs text-text-secondary">{version}</span>
        )}
      </div>

      {/* 中左：十组模块菜单 */}
      <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
        {MODULE_GROUPS.map((group) => {
          const expanded = openGroup === group.group;
          return (
            <div
              key={group.group}
              className="relative shrink-0"
              ref={expanded ? menuRef : undefined}
            >
              <button
                type="button"
                onClick={() => setOpenGroup(expanded ? null : group.group)}
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
                {group.label}
              </button>

              {expanded && (
                <div
                  role="menu"
                  className="absolute left-0 top-full z-[6000] min-w-48 rounded-b-md border border-border bg-surface py-1 shadow-window-active"
                >
                  {group.items.map((item) => (
                    <button
                      key={item.route}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        onOpen(item.route);
                        setOpenGroup(null);
                      }}
                      className={cn(
                        "flex w-full cursor-pointer items-center gap-2 px-2 py-1 text-left text-[13px] text-text-secondary",
                        "transition-colors duration-200 ease-out outline-none",
                        "hover:bg-background/70 hover:text-accent",
                        "focus-visible:bg-background/70 focus-visible:text-accent focus-visible:outline-none",
                      )}
                    >
                      <span className="shrink-0">{item.icon}</span>
                      <span className="truncate">{item.label}</span>
                      {openRoutes.has(item.route) && (
                        <span
                          aria-hidden="true"
                          className="ml-auto h-1 w-1 shrink-0 rounded-full bg-accent"
                        />
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {/* 右：健康点 + me 名称 + 退出 */}
      <div className="flex shrink-0 items-center gap-2 pl-2">
        {healthMeta && (
          <button
            type="button"
            onClick={() => onOpen("/status")}
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

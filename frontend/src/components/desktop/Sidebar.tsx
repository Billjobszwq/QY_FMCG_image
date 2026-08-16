/**
 * Sidebar：桌面左侧 220px 固定导航栏（v3 基础层）。
 *
 * —— 分组可折叠（本地 state）；条目 = 图标 + 中文 label；
 * —— hover 文字切 accent（accent 仅交互态）；
 * —— 已打开窗口（openRoutes 命中）= 选中态：左侧 2px accent 条 +
 *    文字 text-primary；
 * —— 底部用户区：登录身份名 + 退出（ghost 按钮）；未登录显示提示。
 * —— 颜色一律令牌：bg-surface / border-border / text-*；无渐变无毛玻璃。
 */
import { useState } from "react";
import { cn } from "@/lib/utils";
import { MODULE_GROUPS } from "@/modules/registry";
import type { ModuleGroup, ModuleItem } from "@/modules/registry";
import { useAuth } from "@/store/auth";
import { Button } from "@/components/ui/button";

/** 分组折叠箭头：展开朝下，折叠朝右（rotate -90°）。 */
function ChevronGlyph({ collapsed }: { collapsed: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn(
        "h-3 w-3 transition-transform duration-200 ease-out",
        collapsed && "-rotate-90",
      )}
    >
      <path d="M4.4 6.2 L8 9.8 L11.6 6.2" />
    </svg>
  );
}

function SidebarItem({
  item,
  open,
  onOpen,
}: {
  item: ModuleItem;
  open: boolean;
  onOpen: (route: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(item.route)}
      aria-current={open ? "page" : undefined}
      title={item.label}
      className={cn(
        "relative flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1 text-[13px]",
        "transition-colors duration-200 ease-out outline-none",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        open
          ? "bg-background text-text-primary"
          : "text-text-secondary hover:text-accent",
      )}
    >
      {/* 选中态：左侧 2px accent 条 */}
      {open && (
        <span
          aria-hidden="true"
          className="absolute left-0 top-1/2 h-3.5 w-0.5 -translate-y-1/2 rounded-full bg-accent"
        />
      )}
      <span className="shrink-0">{item.icon}</span>
      <span className="truncate">{item.label}</span>
    </button>
  );
}

function SidebarGroup({
  group,
  collapsed,
  onToggle,
  openRoutes,
  onOpen,
}: {
  group: ModuleGroup;
  collapsed: boolean;
  onToggle: () => void;
  openRoutes: Set<string>;
  onOpen: (route: string) => void;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="flex w-full cursor-pointer items-center gap-1 rounded px-2 py-1 text-xs font-medium text-text-secondary transition-colors duration-200 ease-out outline-none hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      >
        <ChevronGlyph collapsed={collapsed} />
        <span>{group.label}</span>
      </button>
      {!collapsed && (
        <div className="mt-0.5 space-y-0.5">
          {group.items.map((item) => (
            <SidebarItem
              key={item.route}
              item={item}
              open={openRoutes.has(item.route)}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export interface SidebarProps {
  /** 当前已打开窗口对应的路由集合（桌面层传入）。 */
  openRoutes: Set<string>;
  /** 点击条目：由桌面层打开对应窗口。 */
  onOpen: (route: string) => void;
}

export function Sidebar({ openRoutes, onOpen }: SidebarProps) {
  // 折叠状态按 group 键记录；缺省全部展开
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const me = useAuth((s) => s.me);
  const logout = useAuth((s) => s.logout);

  return (
    <aside className="flex h-full w-[220px] shrink-0 flex-col border-r border-border bg-surface">
      {/* 品牌行 */}
      <div className="border-b border-border px-3 py-2.5">
        <div className="font-display text-sm font-bold text-text-primary">
          TaaS 工作台
        </div>
        <div className="text-[11px] text-text-secondary">
          识别 · 数据 · 工作流
        </div>
      </div>

      {/* 导航区（可滚动） */}
      <nav className="flex-1 space-y-2 overflow-y-auto px-2 py-2">
        {MODULE_GROUPS.map((group) => (
          <SidebarGroup
            key={group.group}
            group={group}
            collapsed={collapsed[group.group] ?? false}
            onToggle={() =>
              setCollapsed((prev) => ({
                ...prev,
                [group.group]: !(prev[group.group] ?? false),
              }))
            }
            openRoutes={openRoutes}
            onOpen={onOpen}
          />
        ))}
      </nav>

      {/* 底部用户区 */}
      <div className="border-t border-border px-3 py-2">
        {me ? (
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[13px] text-text-primary">
                {me.actor}
              </div>
              <div className="text-[11px] text-text-secondary">{me.role}</div>
            </div>
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
        ) : (
          <div className="text-xs text-text-secondary">未登录</div>
        )}
      </div>
    </aside>
  );
}

export default Sidebar;

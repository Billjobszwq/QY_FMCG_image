import type { PointerEvent as ReactPointerEvent } from "react";
import { cn } from "@/lib/utils";
import type { WindowState } from "@/store/windowStore";
import {
  AppGlyph,
  CloseGlyph,
  MaximizeGlyph,
  MinimizeGlyph,
  RestoreGlyph,
} from "@/components/icons";

interface TitleBarProps {
  win: WindowState;
  isActive: boolean;
  /** 在标题栏按下指针时启动窗口拖拽（最大化时为 undefined，禁止拖拽）。 */
  onStartDrag?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onMinimize: () => void;
  onToggleMaximize: () => void;
  onClose: () => void;
}

function WindowControlButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      /* 阻止冒泡：避免触发标题栏拖拽 */
      onPointerDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      className={cn(
        "flex h-6 w-6 cursor-pointer items-center justify-center rounded-md",
        "text-text-secondary transition-colors duration-200 ease-out",
        "hover:bg-background hover:text-accent",
        "focus-visible:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        "active:scale-[0.97]",
      )}
    >
      {children}
    </button>
  );
}

/**
 * 窗口标题栏：高度 40px（--titlebar-height）。
 * —— 按住拖动窗口；双击切换最大化 / 还原
 * —— 右侧控制按钮：最小化（—）、最大化（□）/ 还原、关闭（×）
 */
export function TitleBar({
  win,
  isActive,
  onStartDrag,
  onMinimize,
  onToggleMaximize,
  onClose,
}: TitleBarProps) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-2 border-b border-border bg-surface px-2 pl-3 select-none",
        !win.isMaximized && "cursor-grab active:cursor-grabbing",
      )}
      style={{ height: "var(--titlebar-height)" }}
      onPointerDown={onStartDrag}
      onDoubleClick={onToggleMaximize}
    >
      <span
        className={cn(
          "flex h-4 w-4 items-center justify-center",
          isActive ? "text-text-primary" : "text-text-secondary",
        )}
      >
        {win.icon ?? <AppGlyph className="h-3.5 w-3.5" />}
      </span>
      <span
        className={cn(
          "font-display truncate text-[13px] font-bold tracking-tight",
          isActive ? "text-text-primary" : "text-text-secondary",
        )}
      >
        {win.title}
      </span>

      <div className="ml-auto flex items-center gap-1">
        <WindowControlButton label="最小化" onClick={onMinimize}>
          <MinimizeGlyph />
        </WindowControlButton>
        <WindowControlButton
          label={win.isMaximized ? "还原" : "最大化"}
          onClick={onToggleMaximize}
        >
          {win.isMaximized ? <RestoreGlyph /> : <MaximizeGlyph />}
        </WindowControlButton>
        {win.closable && (
          <WindowControlButton label="关闭" onClick={onClose}>
            <CloseGlyph />
          </WindowControlButton>
        )}
      </div>
    </div>
  );
}

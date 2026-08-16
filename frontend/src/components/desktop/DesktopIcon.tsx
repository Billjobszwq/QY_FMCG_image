import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/**
 * 桌面图标（受控窗口启动器，v4 交互范式）。
 *
 * —— 单击 = onSelect（仅选中，不开窗）；
 * —— 双击 / Enter / Space = onOpen（开窗或置前）；
 * —— selected 态：tile 边框 border-strong + 底 bg-background；
 * —— isOpen 态：label 右侧 4px accent 圆点（选中态允许使用 accent）。
 *
 * 与旧版区别：不再自持窗口状态 / 直接读 store，改由桌面层统一受控，
 * 与顶部菜单栏共用同一份 openRoutes / 选中态。颜色一律令牌；无渐变无毛玻璃。
 */
export interface DesktopIconProps {
  /** 模块图标（registry 的 icon，currentColor，不硬编码颜色）。 */
  icon: ReactNode;
  /** 中文模块名。 */
  label: string;
  /** 是否处于选中态（单击选中）。 */
  selected: boolean;
  /** 对应窗口是否已打开（含最小化）。 */
  isOpen: boolean;
  /** 单击回调：仅更新选中态。 */
  onSelect: () => void;
  /** 双击 / Enter / Space 回调：开窗或置前。 */
  onOpen: () => void;
}

export function DesktopIcon({
  icon,
  label,
  selected,
  isOpen,
  onSelect,
  onOpen,
}: DesktopIconProps) {
  return (
    <button
      type="button"
      data-desktop-icon
      onClick={onSelect}
      onDoubleClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      aria-pressed={selected}
      title={label}
      className={cn(
        "group flex w-20 cursor-pointer flex-col items-center gap-1.5 rounded-lg p-2",
        "transition-colors duration-200 ease-out outline-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
      )}
    >
      <span
        className={cn(
          "flex h-11 w-11 items-center justify-center rounded-lg border text-text-primary",
          "transition-colors duration-200 ease-out group-hover:border-border-strong",
          selected ? "border-border-strong bg-background" : "border-border bg-surface",
        )}
      >
        {icon}
      </span>
      <span className="flex max-w-full items-center gap-1">
        <span
          className={cn(
            "truncate text-xs transition-colors duration-200 ease-out",
            selected
              ? "text-text-primary"
              : "text-text-secondary group-hover:text-text-primary",
          )}
        >
          {label}
        </span>
        {isOpen && (
          <span
            aria-hidden="true"
            className="h-1 w-1 shrink-0 rounded-full bg-accent"
          />
        )}
      </span>
    </button>
  );
}

export default DesktopIcon;

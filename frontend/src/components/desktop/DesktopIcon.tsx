import { cn } from "@/lib/utils";
import {
  useWindowManager,
  type WindowDescriptor,
} from "@/store/windowStore";

/**
 * 桌面图标（窗口启动器）。
 * —— 窗口未打开：按默认位置 / 尺寸打开
 * —— 窗口已打开（含最小化）：置前 / 还原
 * 图标为简单 SVG 占位，待替换为正式图标库。
 */
export function DesktopIcon({
  descriptor,
  label,
}: {
  descriptor: WindowDescriptor;
  label: string;
}) {
  const isOpen = useWindowManager((s) => Boolean(s.windows[descriptor.id]));

  const handleClick = () => {
    /* 点击时再取最新状态，避免闭包过期 */
    const { windows, openWindow, bringToFront, restoreWindow } =
      useWindowManager.getState();
    const existing = windows[descriptor.id];
    if (!existing) openWindow(descriptor);
    else if (existing.isMinimized) restoreWindow(descriptor.id);
    else bringToFront(descriptor.id);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-pressed={isOpen}
      className={cn(
        "group flex w-20 cursor-pointer flex-col items-center gap-1.5 rounded-lg p-2",
        "transition-colors duration-200 ease-out",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "hover:bg-surface",
      )}
    >
      <span
        className={cn(
          "flex h-11 w-11 items-center justify-center rounded-lg border bg-surface text-text-primary",
          "transition-colors duration-200 ease-out",
          isOpen ? "border-border-strong" : "border-border",
          "group-hover:border-accent",
        )}
      >
        {descriptor.icon}
      </span>
      <span className="max-w-full truncate text-xs text-text-secondary transition-colors duration-200 ease-out group-hover:text-text-primary">
        {label}
      </span>
    </button>
  );
}

import { cn } from "@/lib/utils";
import {
  useOrderedWindows,
  useWindowManager,
  type WindowState,
} from "@/store/windowStore";
import { AppGlyph, HedgehogMark } from "@/components/icons";
import { Kbd } from "@/components/ui/kbd";

/** 按平台渲染修饰键：macOS ⌘，其余 Ctrl（与 useKeyboardShortcuts 实际生效键一致）。 */
function useModKeyLabel() {
  if (typeof navigator === "undefined") return "Ctrl";
  return /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
}

function TaskbarItem({ win }: { win: WindowState }) {
  const isActive = useWindowManager((s) => s.activeId === win.id);
  const { restoreWindow, bringToFront, minimizeWindow } =
    useWindowManager.getState();

  /* Windows 语义：已最小化 → 还原；当前聚焦 → 最小化；其余 → 置前 */
  const handleClick = () => {
    if (win.isMinimized) restoreWindow(win.id);
    else if (isActive) minimizeWindow(win.id);
    else bringToFront(win.id);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      title={win.title}
      aria-pressed={isActive}
      className={cn(
        "relative flex h-8 max-w-44 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-[13px]",
        "transition-colors duration-200 ease-out",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        isActive
          ? /* 选中态允许使用 accent：底部短横线标记聚焦窗口 */
            "bg-background text-text-primary shadow-sm"
          : "text-text-secondary hover:bg-background/70 hover:text-accent",
        win.isMinimized && "opacity-60",
      )}
    >
      <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
        {win.icon ?? <AppGlyph className="h-3.5 w-3.5" />}
      </span>
      <span className="truncate">{win.title}</span>
      <span
        className={cn(
          "absolute bottom-0.5 left-1/2 h-0.5 w-4 -translate-x-1/2 rounded-full",
          isActive ? "bg-accent" : "bg-transparent",
        )}
        aria-hidden="true"
      />
    </button>
  );
}

/**
 * 底部任务栏：高 48px（--taskbar-height），半透明（无毛玻璃）。
 * —— 列出所有已打开窗口；最小化的窗口在此点击还原
 */
export function Taskbar() {
  const windows = useOrderedWindows();
  const modKey = useModKeyLabel();

  return (
    <footer
      className="absolute inset-x-0 bottom-0 z-[5000] border-t border-border shadow-taskbar"
      style={{
        height: "var(--taskbar-height)",
        background:
          "color-mix(in srgb, var(--color-surface) 86%, transparent)",
      }}
    >
      <div className="flex h-full items-center gap-1 px-2">
        {/* 品牌标记：刺猬侧面剪影（与 favicon / HedgehogMark 同源），
            内置按钮语义与 aria-label，预留开始菜单入口；
            默认墨色，hover / focus 过渡到 accent（状态色纪律） */}
        <span className="mr-1 shrink-0 text-text-primary">
          <HedgehogMark />
        </span>

        <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {windows.map((win) => (
            <TaskbarItem key={win.id} win={win} />
          ))}
        </nav>

        <span className="hidden shrink-0 items-center gap-1 pr-1 text-[11px] text-text-secondary sm:flex">
          <Kbd>{modKey}</Kbd>
          <Kbd>W</Kbd>
          关闭
          <Kbd>{modKey}</Kbd>
          <Kbd>M</Kbd>
          最小化
        </span>
      </div>
    </footer>
  );
}

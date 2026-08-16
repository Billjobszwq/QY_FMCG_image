import { AnimatePresence } from "framer-motion";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { useOrderedWindows, useWindowManager } from "@/store/windowStore";
import { useDesktopSize } from "@/hooks/useDesktopSize";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { AppWindow } from "@/components/window/AppWindow";
import { Taskbar } from "./Taskbar";

/**
 * 桌面容器：
 * —— 背景使用 --color-background + 极淡点阵纹理（手工感）
 * —— 窗口自由重叠；点击桌面空白处不触发自动排列
 * —— 页面滚动被锁定，滚动仅发生在窗口内部
 *
 * children 渲染在窗口层之下（桌面图标层）。
 *
 * v4 交互范式：
 * —— showTaskbar=false 时进入「无壳」登录闸门：仅点阵背景 + 窗口层（登录窗），
 *    不渲染图标层内容与任务栏；
 * —— onBackgroundDoubleClick：双击目标恰为图标背景层本身时触发（用于清除选中），
 *    命中图标 / 窗口等子元素不触发。
 */
export interface DesktopProps {
  children?: ReactNode;
  /** 双击桌面背景层本身时回调（清除图标选中）。 */
  onBackgroundDoubleClick?: () => void;
  /** 是否渲染底部任务栏；登录闸门无壳态传 false。默认 true。 */
  showTaskbar?: boolean;
}

export function Desktop({
  children,
  onBackgroundDoubleClick,
  showTaskbar = true,
}: DesktopProps) {
  useKeyboardShortcuts();
  const windows = useOrderedWindows();
  const desktopSize = useDesktopSize();
  /** 无任务栏时（登录闸门）窗口层延伸到底，不再预留任务栏高度。 */
  const bottomInset = showTaskbar ? "var(--taskbar-height)" : "0px";

  /* 视口变化时让最大化窗口跟随新尺寸 */
  useEffect(() => {
    useWindowManager.getState().syncMaximizedSizes();
  }, [desktopSize]);

  return (
    <div className="desktop-dots relative h-full w-full overflow-hidden bg-background">
      {/* 桌面图标层（位于窗口之下）：双击空白（非图标）→ 清除选中 */}
      <div
        className="absolute inset-x-0 top-0 overflow-y-auto"
        style={{ bottom: bottomInset }}
        onDoubleClick={(e) => {
          const t = e.target as HTMLElement;
          if (!t.closest("[data-desktop-icon]")) onBackgroundDoubleClick?.();
        }}
      >
        {children}
      </div>

      {/* 窗口层：层本身不拦截指针，命中交给各窗口（否则盖住图标层） */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0"
        style={{ bottom: bottomInset }}
      >
        <AnimatePresence>
          {windows.map((win) => (
            <AppWindow key={win.id} win={win} />
          ))}
        </AnimatePresence>
      </div>

      {showTaskbar && <Taskbar />}
    </div>
  );
}

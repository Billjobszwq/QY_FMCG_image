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
 * children 渲染在窗口层之下（如桌面图标栏）。
 */
export function Desktop({ children }: { children?: ReactNode }) {
  useKeyboardShortcuts();
  const windows = useOrderedWindows();
  const desktopSize = useDesktopSize();

  /* 视口变化时让最大化窗口跟随新尺寸 */
  useEffect(() => {
    useWindowManager.getState().syncMaximizedSizes();
  }, [desktopSize]);

  return (
    <div className="desktop-dots relative h-full w-full overflow-hidden bg-background">
      {/* 桌面层（图标等，位于窗口之下） */}
      <div
        className="absolute inset-x-0 top-0"
        style={{ bottom: "var(--taskbar-height)" }}
      >
        {children}
      </div>

      {/* 窗口层 */}
      <div
        className="absolute inset-x-0 top-0"
        style={{ bottom: "var(--taskbar-height)" }}
      >
        <AnimatePresence>
          {windows.map((win) => (
            <AppWindow key={win.id} win={win} />
          ))}
        </AnimatePresence>
      </div>

      <Taskbar />
    </div>
  );
}

import { useEffect } from "react";
import { getWindowManager } from "@/store/windowStore";

/**
 * 全局键盘快捷键：
 * —— Ctrl/Cmd + W：关闭当前聚焦窗口
 * —— Ctrl/Cmd + M：最小化当前聚焦窗口
 * —— Esc：取消聚焦 / 高亮状态
 *
 * 注意：部分浏览器（尤其 Chrome / Safari）会优先拦截 Cmd+W 关闭标签页，
 * preventDefault 无法保证生效；应用内逻辑已完整实现。
 */
export function useKeyboardShortcuts() {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();
      const { activeId, closeWindow, minimizeWindow, setActive } =
        getWindowManager();

      if (mod && key === "w" && activeId) {
        e.preventDefault();
        closeWindow(activeId);
        return;
      }
      if (mod && key === "m" && activeId) {
        e.preventDefault();
        minimizeWindow(activeId);
        return;
      }
      if (e.key === "Escape") {
        setActive(null);
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

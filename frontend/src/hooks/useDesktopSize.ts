import { useEffect, useState } from "react";
import { TASKBAR_HEIGHT } from "@/store/windowStore";

/** 桌面可用区域尺寸（视口减去任务栏高度），随窗口 resize 更新。 */
export function useDesktopSize() {
  const [size, setSize] = useState(() => ({
    width: window.innerWidth,
    height: window.innerHeight - TASKBAR_HEIGHT,
  }));

  useEffect(() => {
    const onResize = () =>
      setSize({
        width: window.innerWidth,
        height: window.innerHeight - TASKBAR_HEIGHT,
      });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return size;
}

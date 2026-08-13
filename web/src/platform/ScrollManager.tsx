// OSV5.1 C-7（导航滚动契约）：路由切换的滚动连续性 + 焦点落点 + 屏幕阅读器播报。
//
// 背景：classic HashRouter（react-router-dom 6.26，非 data router）没有
// <ScrollRestoration/> 可用；window 是唯一滚动容器（.main-col 无 overflow），
// 导航只改 location.hash，旧滚动位置被新页面继承并被浏览器钳制
// （Import Center y=2124 → /status 停在 ~1504）。
//
// 本组件按 location.key 统一管理：
//   - PUSH/REPLACE 且 pathname 变化 → scrollTo(0,0)，焦点移到新页面标题
//     （h1；无 h1 时回退 h2，再无则内容区；缺 tabindex 时补 tabindex=-1），
//     并用 aria-live polite 播报页面标题
//   - POP（back/forward）→ 恢复该 history key 保存的滚动位置
// 主导航 / 二级导航 / Supervisor UIIntent navigate / 普通链接 / <Navigate>
// 重定向全部经过 router，故该单一 effect 覆盖全部导航入口。
import { useEffect, useRef, useState } from "react";
import {
  NavigationType, useLocation, useNavigationType,
} from "react-router-dom";

// C-7.1：接管浏览器默认滚动恢复，全部由本组件决定。模块加载即生效
// （早于首次渲染），保证刷新/深链时浏览器不抢先恢复旧位置。
if (typeof window !== "undefined"
    && "scrollRestoration" in window.history) {
  window.history.scrollRestoration = "manual";
}

// 每个 history 条目的滚动位置（location.key → scrollY），上限防止无界增长。
const savedPositions = new Map<string, number>();
const POSITION_LIMIT = 100;
// lazy 路由先渲染 Suspense fallback，标题要等 chunk 挂载后才存在，故轮询。
const HEADING_POLL_MS = 50;
const HEADING_POLL_MAX = 40; // 50ms × 40 = 2s

function contentColumn(): Element | null {
  return document.querySelector(".main-col");
}

function pageHeading(): HTMLElement | null {
  const col = contentColumn();
  if (!col) return null;
  return col.querySelector<HTMLElement>("h1")
    ?? col.querySelector<HTMLElement>("h2");
}

// 聚焦目标：非交互元素（标题/内容区）原生不可聚焦，缺 tabindex 时补 -1。
// preventScroll=false：已 scrollTo(0,0)，允许浏览器按焦点微调位置。
function focusTarget(el: HTMLElement) {
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: false });
}

export default function ScrollManager() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const prevKeyRef = useRef<string | null>(null);
  const prevPathnameRef = useRef<string | null>(null);
  const processedKeyRef = useRef<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    const prevKey = prevKeyRef.current;
    const prevPathname = prevPathnameRef.current;
    // StrictMode 开发态同 key 双跑识别为重放（重复幂等动作），
    // 不误判为“同 pathname 新导航”。
    const isRerun = processedKeyRef.current === location.key;
    prevKeyRef.current = location.key;
    prevPathnameRef.current = location.pathname;
    processedKeyRef.current = location.key;

    // 离开前记录该条目的滚动位置，供 back/forward 恢复。
    if (prevKey && prevKey !== location.key) {
      savedPositions.set(prevKey, window.scrollY);
      while (savedPositions.size > POSITION_LIMIT) {
        const oldest = savedPositions.keys().next().value;
        if (oldest === undefined) break;
        savedPositions.delete(oldest);
      }
    }

    if (navigationType === NavigationType.Pop) {
      // C-7.2：back/forward 恢复该 history key 保存的滚动位置。
      window.scrollTo(0, savedPositions.get(location.key) ?? 0);
      return undefined;
    }

    // PUSH/REPLACE：仅 pathname 实际变化时重置（同路径的 query/search
    // 更新不打断用户位置）。
    if (!isRerun && prevPathname !== null
        && prevPathname === location.pathname) {
      return undefined;
    }

    window.scrollTo(0, 0);

    // C-7.3：焦点落点 + aria-live 播报。标题可能尚未挂载（lazy），轮询。
    let cancelled = false;
    const tryLand = (): boolean => {
      if (cancelled) return true;
      const heading = pageHeading();
      if (!heading) return false;
      if (document.activeElement !== heading) focusTarget(heading);
      setAnnouncement(heading.textContent?.trim() || location.pathname);
      return true;
    };
    if (tryLand()) return undefined;

    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (tryLand()) {
        window.clearInterval(timer);
        return;
      }
      if (attempts >= HEADING_POLL_MAX) {
        window.clearInterval(timer);
        // 无 h1/h2 的页面（404、reference.echo 等）：焦点落到内容区，
        // 播报路径，保证键盘/读屏用户始终有落点。
        const col = contentColumn();
        if (col && !cancelled) {
          focusTarget(col as HTMLElement);
          setAnnouncement(`已切换页面 ${location.pathname}`);
        }
      }
    }, HEADING_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [location.key, location.pathname, navigationType]);

  return (
    <div aria-live="polite" style={{
      position: "absolute", width: 1, height: 1, margin: -1, padding: 0,
      overflow: "hidden", clip: "rect(0 0 0 0)", whiteSpace: "nowrap",
      border: 0,
    }}>{announcement}</div>
  );
}

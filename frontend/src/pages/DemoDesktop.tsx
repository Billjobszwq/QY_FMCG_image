import { Suspense, useCallback, useEffect, useMemo, useRef } from "react";
import { Desktop } from "@/components/desktop/Desktop";
import { Sidebar } from "@/components/desktop/Sidebar";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { HedgehogLoader } from "@/components/ui/loader";
import { MODULE_BY_ROUTE } from "@/modules/registry";
import { useAuth } from "@/store/auth";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   产品桌面壳（v3 集成）：Sidebar(左) + 桌面区(右，窗口层) + Taskbar(底)

   —— 启动时 auth.refresh() 恢复本机登录会话；
   —— 未登录（me 为 null）：桌面只保留登录窗口（closable=false，不可关闭）；
   —— 登录成功：关闭登录窗，默认打开 /home 与 /status 两个模块窗口；
   —— Sidebar 点击模块：openWindow({ id: 路由键, title: 模块 label,
      960×640, 层叠偏移 })；已打开则 bringToFront（最小化则还原）；
   —— openRoutes 由 store 的打开顺序（order）计算，供 Sidebar 选中态使用。

   数据红线：一切业务数据走同源 /api/v1/*（src/lib/api.ts），
   本壳层不含任何样本 / 假数据。
   ========================================================================== */

/** 模块窗口默认尺寸（信息密度优先）。 */
const MODULE_WINDOW_SIZE = { width: 960, height: 640 };
/** 模块窗口最小尺寸。 */
const MODULE_MIN_SIZE = { width: 560, height: 420 };
/** 层叠偏移基准与步长（每次新开窗口向右下错一格）。 */
const CASCADE_BASE = { x: 32, y: 20 };
const CASCADE_STEP = 28;
/** 登录窗口 id（页面内 NeedLoginState 打开登录窗时共用同一 id）。 */
const LOGIN_WINDOW_ID = "login";
/** Sidebar 固定宽度（与 Sidebar 组件 w-[220px] 一致），登录窗居中用。 */
const SIDEBAR_WIDTH = 220;

/** 模块窗口内容：路由级懒加载页面 + 刺猬加载兜底（拒绝通用旋转圈）。 */
function ModuleContent({ route }: { route: string }) {
  const item = MODULE_BY_ROUTE[route];
  if (!item) return null;
  const Page = item.Page;
  return (
    <Suspense
      fallback={
        <div className="flex h-full w-full items-center justify-center">
          <HedgehogLoader />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}

export default function DemoDesktop() {
  const me = useAuth((s) => s.me);
  const checking = useAuth((s) => s.checking);
  const refresh = useAuth((s) => s.refresh);
  const order = useWindowManager((s) => s.order);

  /** 层叠序号：每新开一个窗口递增（取模防止无限漂移出屏）。 */
  const cascadeRef = useRef(0);
  const nextCascade = useCallback(() => {
    const n = cascadeRef.current % 7;
    cascadeRef.current += 1;
    return {
      x: CASCADE_BASE.x + n * CASCADE_STEP,
      y: CASCADE_BASE.y + n * CASCADE_STEP,
    };
  }, []);

  /* 启动时恢复登录会话（401 / 网络错误 → me=null，由壳层统一处理） */
  useEffect(() => {
    void refresh();
  }, [refresh]);

  /** 打开模块窗口（960×640，层叠偏移）；已打开则不重复创建。 */
  const openModuleWindow = useCallback(
    (route: string) => {
      const item = MODULE_BY_ROUTE[route];
      if (!item) return;
      const wm = useWindowManager.getState();
      if (wm.windows[route]) return;
      wm.openWindow({
        id: route,
        title: item.label,
        icon: item.icon,
        content: <ModuleContent route={route} />,
        defaultPosition: nextCascade(),
        defaultSize: MODULE_WINDOW_SIZE,
        minWidth: MODULE_MIN_SIZE.width,
        minHeight: MODULE_MIN_SIZE.height,
      });
    },
    [nextCascade],
  );

  /** 打开登录窗口（未登录时桌面唯一窗口；closable=false 隐藏关闭钮）。 */
  const openLoginWindow = useCallback(() => {
    const wm = useWindowManager.getState();
    if (wm.windows[LOGIN_WINDOW_ID]) {
      if (wm.windows[LOGIN_WINDOW_ID].isMinimized) {
        wm.restoreWindow(LOGIN_WINDOW_ID);
      } else {
        wm.bringToFront(LOGIN_WINDOW_ID);
      }
      return;
    }
    wm.openWindow({
      id: LOGIN_WINDOW_ID,
      title: "平台登录",
      content: (
        <div className="flex h-full w-full items-center justify-center p-4">
          <LoginWindow
            onLoggedIn={() =>
              useWindowManager.getState().closeWindow(LOGIN_WINDOW_ID)
            }
          />
        </div>
      ),
      defaultPosition: {
        x: Math.max(
          16,
          Math.round((window.innerWidth - SIDEBAR_WIDTH - 360) / 2),
        ),
        y: 96,
      },
      defaultSize: { width: 360, height: 460 },
      resizable: false,
      closable: false,
    });
  }, []);

  const loggedIn = me !== null;

  /* 会话切换 → 窗口集合：
     登录后关闭登录窗、默认打开 /home 与 /status；
     退出后关闭全部业务窗口（登录窗由下方守护效果保证在场）。 */
  useEffect(() => {
    if (checking) return; // 会话恢复中：等结果出来再统一处理，避免闪烁
    const wm = useWindowManager.getState();
    if (loggedIn) {
      wm.closeWindow(LOGIN_WINDOW_ID);
      openModuleWindow("/home");
      openModuleWindow("/status");
    } else {
      for (const id of wm.order) {
        if (id !== LOGIN_WINDOW_ID) wm.closeWindow(id);
      }
      openLoginWindow();
    }
  }, [checking, loggedIn, openLoginWindow, openModuleWindow]);

  /* 未登录守护：登录窗口必须始终在场（closable=false 只隐藏关闭钮，
     ⌘W 等旁路关闭后在此自动补开）。 */
  const loginOpen = useWindowManager((s) =>
    Boolean(s.windows[LOGIN_WINDOW_ID]),
  );
  useEffect(() => {
    if (!checking && !loggedIn && !loginOpen) openLoginWindow();
  }, [checking, loggedIn, loginOpen, openLoginWindow]);

  /** Sidebar 点击：未登录 → 打开登录窗；已打开 → 置前/还原；否则新开。 */
  const handleOpenRoute = useCallback(
    (route: string) => {
      if (!useAuth.getState().me) {
        openLoginWindow();
        return;
      }
      const wm = useWindowManager.getState();
      const existing = wm.windows[route];
      if (existing) {
        if (existing.isMinimized) wm.restoreWindow(route);
        else wm.bringToFront(route);
        return;
      }
      openModuleWindow(route);
    },
    [openLoginWindow, openModuleWindow],
  );

  /* 已打开窗口对应的路由集合（Sidebar 选中态；openRoutes 按 store order 计算） */
  const openRoutes = useMemo(
    () => new Set(order.filter((id) => id.startsWith("/"))),
    [order],
  );

  return (
    <div className="flex h-full w-full overflow-hidden bg-background">
      {/* 左侧导航：分组模块清单 + 底部登录身份区 */}
      <Sidebar openRoutes={openRoutes} onOpen={handleOpenRoute} />

      {/* 桌面区：窗口层 + 底部任务栏（Taskbar 由 Desktop 内嵌渲染） */}
      <main className="relative min-w-0 flex-1">
        <Desktop>
          {/* 会话恢复中：桌面中央刺猬加载（拒绝通用旋转圈） */}
          {checking && !me && (
            <div className="flex h-full w-full items-center justify-center">
              <HedgehogLoader />
            </div>
          )}
        </Desktop>
      </main>
    </div>
  );
}

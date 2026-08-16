import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Desktop } from "@/components/desktop/Desktop";
import { DesktopIcon } from "@/components/desktop/DesktopIcon";
import { TopMenuBar } from "@/components/desktop/TopMenuBar";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { HedgehogLoader } from "@/components/ui/loader";
import { MODULE_BY_ROUTE, MODULE_GROUPS } from "@/modules/registry";
import { useAuth } from "@/store/auth";
import { useWindowManager } from "@/store/windowStore";

/* ============================================================================
   产品桌面壳（v4 交互范式）：TopMenuBar(顶) + 桌面区(图标层+窗口层) + Taskbar(底)

   —— 启动时 auth.refresh() 恢复本机登录会话；
   —— 登录闸门（checking / 未登录）必须「无壳」：无菜单栏、无图标、无任务栏，
      仅居中登录窗（checking 期间为居中刺猬加载）；
   —— 登录成功：关闭登录窗，默认打开 /home 与 /status（保留现状）；
   —— 模块 = 桌面图标：单击仅选中，双击 / Enter / Space 开窗；
      顶部菜单栏分组下拉亦可开窗；已打开窗口在图标与菜单条目上各显一枚 accent 圆点；
   —— openRoutes 由 store 的打开顺序（order）计算，图标与菜单共用。

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
/** 登录窗口尺寸（不可调、不可关）。 */
const LOGIN_WINDOW_SIZE = { width: 360, height: 460 };

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
  /** 桌面图标选中态（单击选中，背景双击清除）。 */
  const [selectedRoute, setSelectedRoute] = useState<string | null>(null);

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

  /** 打开登录窗口（未登录时桌面唯一窗口；closable=false 隐藏关闭钮，居中）。 */
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
          Math.round((window.innerWidth - LOGIN_WINDOW_SIZE.width) / 2),
        ),
        y: Math.max(
          16,
          Math.round((window.innerHeight - LOGIN_WINDOW_SIZE.height) / 2),
        ),
      },
      defaultSize: LOGIN_WINDOW_SIZE,
      resizable: false,
      closable: false,
    });
  }, []);

  const loggedIn = me !== null;

  /* 会话切换 → 窗口集合：
     登录后关闭登录窗、默认打开 /home 与 /status；
     退出后关闭全部业务窗口并清除选中（登录窗由下方守护效果保证在场）。 */
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
      setSelectedRoute(null);
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

  /** 打开模块：未登录 → 打开登录窗；已打开 → 置前/还原；否则新开。 */
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

  /* 已打开窗口对应的路由集合（图标 isOpen 与菜单条目圆点共用；按 store order） */
  const openRoutes = useMemo(
    () => new Set(order.filter((id) => id.startsWith("/"))),
    [order],
  );

  /* —— 登录闸门：会话恢复中 → 无壳桌面 + 居中刺猬加载 —— */
  if (checking && !me) {
    return (
      <div className="desktop-dots relative flex h-full w-full items-center justify-center overflow-hidden bg-background">
        <HedgehogLoader />
      </div>
    );
  }

  /* —— 登录闸门：未登录 → 无壳桌面 + 居中登录窗（保留 ⌘W 旁路守护） —— */
  if (!loggedIn) {
    return <Desktop showTaskbar={false} />;
  }

  /* —— 登录后：TopMenuBar(顶) + 桌面区(图标层+窗口层) + Taskbar(底) —— */
  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-background">
      <TopMenuBar openRoutes={openRoutes} onOpen={handleOpenRoute} />
      <main className="relative min-h-0 flex-1">
        <Desktop onBackgroundDoubleClick={() => setSelectedRoute(null)}>
          {/* 桌面图标层：按 MODULE_GROUPS 分区，单击选中 / 双击开窗 */}
          <div className="flex flex-col pb-2">
            {MODULE_GROUPS.map((group) => (
              <section key={group.group}>
                <div className="px-3 pt-3 text-xs text-text-secondary">
                  {group.label}
                </div>
                <div className="flex flex-wrap gap-1 p-2">
                  {group.items.map((item) => (
                    <DesktopIcon
                      key={item.route}
                      icon={item.icon}
                      label={item.label}
                      selected={selectedRoute === item.route}
                      isOpen={openRoutes.has(item.route)}
                      onSelect={() => setSelectedRoute(item.route)}
                      onOpen={() => handleOpenRoute(item.route)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </Desktop>
      </main>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Desktop } from "@/components/desktop/Desktop";
import { DesktopIcon } from "@/components/desktop/DesktopIcon";
import { ModuleWorkbench } from "@/components/desktop/ModuleWorkbench";
import { TopMenuBar } from "@/components/desktop/TopMenuBar";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { HedgehogLoader } from "@/components/ui/loader";
import {
  AGENT_GROUP,
  CORE_GROUP,
  SUPERVISOR_GLYPH,
  visibleGroups,
} from "@/modules/registry";
import type { ModuleGroup } from "@/modules/registry";
import { useAuth } from "@/store/auth";
import { useModuleTabs } from "@/store/moduleTabs";
import { LOGIN_WINDOW_ID, useWindowManager } from "@/store/windowStore";

/* ============================================================================
   产品桌面壳（v5 交互范式）：TopMenuBar(顶) + 桌面区(图标层+窗口层) + Taskbar(底)

   —— 桌面图标 = 应用：一个模块分组一个图标，双击开窗；窗口内部用
      ModuleWorkbench 的标签页承载子功能（原页面零损失归组）；
   —— 顶部菜单栏只放跨窗口全局真功能（窗口操作 / 帮助 / 主管 Agent
      快捷 / 健康点 / 用户），不放导航下拉；
   —— 启动时 auth.refresh() 恢复本机登录会话；登录闸门（checking / 未登录）
      必须「无壳」：无菜单栏、无图标、无任务栏；
   —— 登录成功：关闭登录窗，默认打开首页组窗口（tab /home）。

   数据红线：一切业务数据走同源 /api/v1/*（src/lib/api.ts），
   本壳层不含任何样本 / 假数据。
   ========================================================================== */

/** 模块分组窗口 id 前缀（窗口 id = "mod:" + groupKey）。 */
const MOD_PREFIX = "mod:";
/** 模块窗口默认尺寸（信息密度优先）。 */
const MODULE_WINDOW_SIZE = { width: 1080, height: 720 };
/** 模块窗口最小尺寸。 */
const MODULE_MIN_SIZE = { width: 760, height: 520 };
/** 层叠偏移基准与步长（每次新开窗口向右下错一格）。 */
const CASCADE_BASE = { x: 32, y: 20 };
const CASCADE_STEP = 28;
/** 登录窗口尺寸（不可调、不可关）。 */
const LOGIN_WINDOW_SIZE = { width: 360, height: 460 };

/** 分组桌面图标：主管组用专用四角星 glyph，其余取组内首项图标。 */
function groupIcon(group: ModuleGroup): ReactNode {
  const node = group.group === AGENT_GROUP ? SUPERVISOR_GLYPH : group.items[0].icon;
  // 桌面图标 tile 比菜单栏大一级：把 16px glyph 放大到 24px。
  return <span className="[&_svg]:h-6 [&_svg]:w-6">{node}</span>;
}

export default function DemoDesktop() {
  const me = useAuth((s) => s.me);
  const checking = useAuth((s) => s.checking);
  const refresh = useAuth((s) => s.refresh);
  const scopes = useAuth((s) => s.scopes);
  const order = useWindowManager((s) => s.order);

  /**
   * 权限投影（04 §6）：只渲染命中 required scope 的分组；
   * scopes 未加载/失败时受限分组 fail-closed 隐藏。
   * 后端仍独立鉴权——隐藏只是体验，不是权限边界。
   */
  const groups = useMemo(() => visibleGroups(scopes), [scopes]);
  /** 桌面图标选中态（单击选中，背景双击清除）。 */
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);

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

  /** 打开模块分组窗口（1080×720，层叠偏移）；已打开则不重复创建。 */
  const openModuleGroupWindow = useCallback(
    (groupKey: string) => {
      // 权限投影守卫：不可见（无权限）分组不创建窗口、不泄漏路由
      const group = groups.find((g) => g.group === groupKey);
      if (!group) return;
      const wm = useWindowManager.getState();
      const id = MOD_PREFIX + groupKey;
      if (wm.windows[id]) return;
      wm.openWindow({
        id,
        title: group.label,
        icon: groupIcon(group),
        content: <ModuleWorkbench groupKey={groupKey} />,
        defaultPosition: nextCascade(),
        defaultSize: MODULE_WINDOW_SIZE,
        minWidth: MODULE_MIN_SIZE.width,
        minHeight: MODULE_MIN_SIZE.height,
      });
    },
    [groups, nextCascade],
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
              useWindowManager.getState().closeWindow(LOGIN_WINDOW_ID, true)
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

  /** 打开 / 置前模块分组窗口；未登录时改开登录窗。 */
  const handleOpenGroup = useCallback(
    (groupKey: string) => {
      if (!useAuth.getState().me) {
        openLoginWindow();
        return;
      }
      const wm = useWindowManager.getState();
      const id = MOD_PREFIX + groupKey;
      const existing = wm.windows[id];
      if (existing) {
        if (existing.isMinimized) wm.restoreWindow(id);
        else wm.bringToFront(id);
        return;
      }
      openModuleGroupWindow(groupKey);
    },
    [openLoginWindow, openModuleGroupWindow],
  );

  const loggedIn = me !== null;

  /* 会话切换 → 窗口集合：
     登录后关闭登录窗、默认打开首页组窗口（tab /home）；
     退出后关闭全部业务窗口（closeAllWindows 保留登录窗）并清除选中。 */
  useEffect(() => {
    if (checking) return; // 会话恢复中：等结果出来再统一处理，避免闪烁
    const wm = useWindowManager.getState();
    if (loggedIn) {
      wm.closeWindow(LOGIN_WINDOW_ID, true);
      useModuleTabs.getState().requestTab(CORE_GROUP, "/home");
      openModuleGroupWindow(CORE_GROUP);
    } else {
      wm.closeAllWindows();
      setSelectedGroup(null);
      openLoginWindow();
    }
  }, [checking, loggedIn, openLoginWindow, openModuleGroupWindow]);

  /* 未登录守护：登录窗口必须始终在场（closable=false 只隐藏关闭钮，
     ⌘W 等旁路关闭后在此自动补开）。 */
  const loginOpen = useWindowManager((s) =>
    Boolean(s.windows[LOGIN_WINDOW_ID]),
  );
  useEffect(() => {
    if (!checking && !loggedIn && !loginOpen) openLoginWindow();
  }, [checking, loggedIn, loginOpen, openLoginWindow]);

  /* 会话中途过期：页面级 401 的「去登录」事件 → 登出回到无壳登录闸门 */
  useEffect(() => {
    const onOpenLogin = () => {
      void useAuth.getState().logout();
    };
    window.addEventListener("platform:open-login", onOpenLogin);
    return () => window.removeEventListener("platform:open-login", onOpenLogin);
  }, []);

  /* 已打开的分组集合（桌面图标 isOpen 圆点用；按 store order） */
  const openGroups = useMemo(
    () =>
      new Set(
        order
          .filter((id) => id.startsWith(MOD_PREFIX))
          .map((id) => id.slice(MOD_PREFIX.length)),
      ),
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
      <TopMenuBar onOpenGroup={handleOpenGroup} />
      <main className="relative min-h-0 flex-1">
        <Desktop onBackgroundDoubleClick={() => setSelectedGroup(null)}>
          {/* 桌面图标层：一组一图标（应用），单击选中 / 双击开窗 */}
          <div className="flex flex-wrap content-start gap-1 p-3">
            {groups.map((group) => (
              <DesktopIcon
                key={group.group}
                icon={groupIcon(group)}
                label={group.label}
                selected={selectedGroup === group.group}
                isOpen={openGroups.has(group.group)}
                onSelect={() => setSelectedGroup(group.group)}
                onOpen={() => handleOpenGroup(group.group)}
              />
            ))}
          </div>
        </Desktop>
      </main>
    </div>
  );
}

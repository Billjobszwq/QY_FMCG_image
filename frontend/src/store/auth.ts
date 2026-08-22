/**
 * 登录会话 store（v3 基础层 + M5 权限投影）。
 *
 * —— me：当前登录身份（/api/v1/auth/me），401 → null（未登录）；
 * —— scopes：/api/v1/iam/whoami 的权限投影（受限模块可见性）；
 *    whoami 未加载或失败 → null → 受限模块 fail-closed 隐藏（04 §6）；
 * —— login：POST /api/v1/auth/login {username, password}，成功后缓存
 *    CSRF token（src/lib/api.ts 内部处理）；失败抛 ApiError 由登录窗口
 *    以 serious 徽章呈现；
 * —— logout：POST /api/v1/auth/logout，清空本地状态（含 scopes）；
 * —— refresh：应用启动/页面刷新后恢复会话并重新拉取 whoami。
 *
 * 纪律：投影只改善体验；所有 API 仍独立鉴权，前端隐藏不是权限控制。
 */
import { create } from "zustand";
import type { AuthMe } from "@/lib/api";
import { fetchAuthLogin, fetchAuthLogout, fetchAuthMe, fetchIamWhoami } from "@/lib/api";

interface AuthState {
  /** 当前登录身份；null 表示未登录（含 401 与从未登录）。 */
  me: AuthMe | null;
  /** 权限 scope 投影；null = 未加载/失败（受限模块 fail-closed 隐藏）。 */
  scopes: string[] | null;
  /** 正在恢复会话（refresh 进行中）。 */
  checking: boolean;
  /** 登录；失败时抛出 ApiError（调用方展示 serious 徽章）。 */
  login: (username: string, password: string) => Promise<void>;
  /** 退出登录（失败也清空本地状态）。 */
  logout: () => Promise<void>;
  /** 拉取 /api/v1/auth/me 与 whoami scopes；401 → me=null。 */
  refresh: () => Promise<void>;
}

async function loadScopes(): Promise<string[] | null> {
  try {
    const who = await fetchIamWhoami();
    return Array.isArray(who.scopes) ? who.scopes : [];
  } catch {
    // 网络失败 / 401 / 500：fail-closed，受限模块不显示
    return null;
  }
}

export const useAuth = create<AuthState>()((set) => ({
  me: null,
  scopes: null,
  checking: true,

  login: async (username, password) => {
    const me = await fetchAuthLogin(username, password);
    const scopes = await loadScopes();
    set({ me, scopes });
  },

  logout: async () => {
    try {
      await fetchAuthLogout();
    } finally {
      set({ me: null, scopes: null });
    }
  },

  refresh: async () => {
    set({ checking: true });
    try {
      const me = await fetchAuthMe();
      const scopes = await loadScopes();
      set({ me, scopes, checking: false });
    } catch {
      // 401 / 网络错误都视为未登录；页面侧自行处理“需要登录”状态
      set({ me: null, scopes: null, checking: false });
    }
  },
}));

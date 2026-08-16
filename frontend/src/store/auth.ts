/**
 * 登录会话 store（v3 基础层）。
 *
 * —— me：当前登录身份（/api/v1/auth/me），401 → null（未登录）；
 * —— login：POST /api/v1/auth/login {username, password}，成功后缓存
 *    CSRF token（src/lib/api.ts 内部处理）；失败抛 ApiError 由登录窗口
 *    以 serious 徽章呈现；
 * —— logout：POST /api/v1/auth/logout，清空本地状态；
 * —— refresh：应用启动/页面刷新后恢复会话。
 */
import { create } from "zustand";
import type { AuthMe } from "@/lib/api";
import { fetchAuthLogin, fetchAuthLogout, fetchAuthMe } from "@/lib/api";

interface AuthState {
  /** 当前登录身份；null 表示未登录（含 401 与从未登录）。 */
  me: AuthMe | null;
  /** 正在恢复会话（refresh 进行中）。 */
  checking: boolean;
  /** 登录；失败时抛出 ApiError（调用方展示 serious 徽章）。 */
  login: (username: string, password: string) => Promise<void>;
  /** 退出登录（失败也清空本地状态）。 */
  logout: () => Promise<void>;
  /** 拉取 /api/v1/auth/me；401 → me=null。 */
  refresh: () => Promise<void>;
}

export const useAuth = create<AuthState>()((set) => ({
  me: null,
  checking: true,

  login: async (username, password) => {
    const me = await fetchAuthLogin(username, password);
    set({ me });
  },

  logout: async () => {
    try {
      await fetchAuthLogout();
    } finally {
      set({ me: null });
    }
  },

  refresh: async () => {
    set({ checking: true });
    try {
      const me = await fetchAuthMe();
      set({ me, checking: false });
    } catch {
      // 401 / 网络错误都视为未登录；页面侧自行处理“需要登录”状态
      set({ me: null, checking: false });
    }
  },
}));

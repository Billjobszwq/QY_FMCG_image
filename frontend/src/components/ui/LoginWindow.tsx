/**
 * LoginWindow：登录窗口内容（v3 基础层）。
 *
 * —— 居中窗口样式卡：细边框 + 小圆角 + shadow-window，surface 底；
 *    无渐变、无毛玻璃；
 * —— 用户名 / 密码 Input + 主按钮；提交调 useAuth().login；
 * —— 错误用 serious 徽章（StatusBadge kind="serious"）；
 * —— 401 → 用户名或口令错误；0 → 网络错误；429 → 触发限流。
 */
import { useState } from "react";
import type { FormEvent } from "react";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/data/StatusBadge";

/** 将登录异常映射为中文文案。 */
function loginErrorOf(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return err.message || "用户名或口令错误";
    if (err.status === 429) return "尝试过于频繁，请稍后再试";
    if (err.status === 0) return err.message || "网络错误，请检查平台服务";
    return err.message || `登录失败（HTTP ${err.status}）`;
  }
  if (err instanceof Error && err.message) return err.message;
  return "登录失败，请稍后重试";
}

export function LoginWindow({
  /** 登录成功回调（桌面层可据此关闭窗口 / 刷新会话）。 */
  onLoggedIn,
  className,
}: {
  onLoggedIn?: () => void;
  className?: string;
}) {
  const login = useAuth((s) => s.login);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      onLoggedIn?.();
    } catch (err) {
      setError(loginErrorOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={cn(
        "w-[320px] rounded-lg border border-border bg-surface p-5 shadow-window",
        className,
      )}
    >
      <h2 className="font-display text-base font-bold text-text-primary">
        平台登录
      </h2>
      <p className="mt-1 text-xs text-text-secondary">
        本机登录会话；写操作将携带 CSRF 校验
      </p>

      <form onSubmit={handleSubmit} className="mt-4 space-y-3">
        <label className="block space-y-1">
          <span className="text-xs text-text-secondary">用户名</span>
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            placeholder="admin"
            autoFocus
          />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-text-secondary">口令</span>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            placeholder="••••••••"
          />
        </label>

        {error && <StatusBadge kind="serious">{error}</StatusBadge>}

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "登录中…" : "登录"}
        </Button>
      </form>
    </div>
  );
}

export default LoginWindow;

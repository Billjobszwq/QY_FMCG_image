/**
 * NeedLoginState：401“需要登录”状态（数据红线）。
 * —— warn 徽章“需要登录” + 说明文字 + 打开登录窗口按钮；
 * —— 登录窗口由桌面层管理，本组件只通过 onOpenLogin 回调请求打开。
 */
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "./StatusBadge";

export function NeedLoginState({
  onOpenLogin,
  className,
}: {
  /** 打开登录窗口的回调。 */
  onOpenLogin: () => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 py-8", className)}>
      <StatusBadge kind="warn">需要登录</StatusBadge>
      <p className="text-xs text-text-secondary">
        该数据需要本机登录会话，请先登录后重试
      </p>
      <Button variant="secondary" size="sm" onClick={onOpenLogin}>
        打开登录窗口
      </Button>
    </div>
  );
}

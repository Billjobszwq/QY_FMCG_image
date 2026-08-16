/**
 * ErrorState：接口错误态（serious 徽章 + 错误说明 + 重试按钮）。
 * 数据红线：网络错误一律走本组件，禁止裸文本 / 通用旋转圈。
 */
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "./StatusBadge";

export function ErrorState({
  message,
  onRetry,
  className,
}: {
  /** 错误说明（穿 text-secondary）；缺省用通用文案。 */
  message?: string;
  /** 重试回调；提供时渲染重试按钮。 */
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn("flex flex-col items-center gap-2 py-8", className)}
    >
      <StatusBadge kind="serious">加载失败</StatusBadge>
      <p className="max-w-[360px] text-center text-xs text-text-secondary">
        {message ?? "数据拉取出错，请稍后重试"}
      </p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          重试
        </Button>
      )}
    </div>
  );
}

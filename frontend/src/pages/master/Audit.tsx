/**
 * 审计日志（IAM · /iam/audit）—— v3 真实数据页面（P6）。
 *
 * 数据源（全部同源 /api/v1/*，无样本数据）：
 * —— GET  /iam/audit          append-only 审计事件（展示最近 50 条）
 * —— POST iam/approval-check  批准矩阵检查：当前身份对指定动作能否批准
 *
 * 状态纪律：401 → NeedLoginState；网络错误 → ErrorState+重试；
 * 加载 / 空态由 ApiTable 内置（HedgehogLoader / HedgehogMascot）。
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, fetchIamGet, fetchIamPost } from "@/lib/api";
import {
  ApiTable,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoginWindow } from "@/components/ui/LoginWindow";
import { getWindowManager } from "@/store/windowStore";

/* ============================================================================
   契约类型（与 web IamMaster.tsx 实际消费字段一致）
   ========================================================================== */

interface AuditEvent {
  audit_id: string;
  occurred_at: string | null;
  actor_id: string;
  action: string;
  resource: string;
  customer_id: string | null;
}

interface ApprovalCheck {
  action: string;
  allowed: boolean;
  username: string;
}

/* ============================================================================
   轻量数据 hook（与 P6 其余页面同构）
   ========================================================================== */

function useApi<T>(fetcher: (() => Promise<T>) | null, deps: readonly unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(fetcher !== null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!fetcher) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    fetcher().then(
      (d) => {
        if (!alive) return;
        setData(d);
        setLoading(false);
      },
      (e: unknown) => {
        if (!alive) return;
        setData(null);
        setError(e);
        setLoading(false);
      },
    );
    return () => {
      alive = false;
    };
    // fetcher 每次渲染重建，不入依赖；由 tick / deps 显式驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

function isNeedLogin(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** 请求桌面层打开登录窗口（openWindow 幂等：已存在则置前）。 */
function openLoginWindow() {
  getWindowManager().openWindow({
    id: "login",
    title: "平台登录",
    content: <LoginWindow />,
    defaultPosition: { x: 320, y: 140 },
    defaultSize: { width: 360, height: 440 },
    resizable: false,
  });
}

/** 区块卡片：细边框小圆角，信息密度优先。 */
function Card({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-md border border-border bg-background p-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-[13px] font-medium text-text-primary">{title}</h2>
        {hint && <p className="text-xs text-text-secondary">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/* ============================================================================
   页面
   ========================================================================== */

export default function AuditPage() {
  const audit = useApi<{ events: AuditEvent[] }>(() => fetchIamGet("/iam/audit"), []);

  const [action, setAction] = useState("production.switch");
  const [check, setCheck] = useState<(ApprovalCheck & { error?: string }) | null>(null);
  const [busy, setBusy] = useState(false);

  async function runCheck() {
    setBusy(true);
    setCheck(null);
    try {
      setCheck((await fetchIamPost("iam/approval-check", { action })) as ApprovalCheck);
    } catch (e) {
      setCheck({ action, allowed: false, username: "", error: errorMessageOf(e) });
    } finally {
      setBusy(false);
    }
  }

  if (isNeedLogin(audit.error)) {
    return (
      <div className="p-5 space-y-4">
        <PageHeader title="审计日志" desc="append-only 审计事件与批准矩阵" />
        <NeedLoginState onOpenLogin={openLoginWindow} />
      </div>
    );
  }

  const cols: ApiTableCol<AuditEvent>[] = [
    {
      key: "occurred_at",
      label: "时间",
      render: (e) => (
        <span className="text-xs text-text-secondary tabular-nums">
          {e.occurred_at ? e.occurred_at.slice(0, 19) : "—"}
        </span>
      ),
    },
    { key: "actor_id", label: "操作者" },
    { key: "action", label: "动作" },
    {
      key: "resource",
      label: "资源",
      render: (e) => <span className="text-xs">{e.resource || "—"}</span>,
    },
    { key: "customer_id", label: "客户", render: (e) => e.customer_id || "—" },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="审计日志"
        desc="append-only 审计事件；高风险动作只能由批准矩阵指定角色批准"
      />

      {/* 批准矩阵检查 */}
      <Card title="批准矩阵检查" hint="检查当前身份对指定动作是否可批准">
        <div className="flex flex-wrap gap-2">
          <Input
            aria-label="动作"
            className="w-72"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
          <Button size="sm" disabled={!action || busy} onClick={() => void runCheck()}>
            {busy ? "检查中…" : "检查我是否可批准"}
          </Button>
        </div>
        {check && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {check.error ? (
              <StatusBadge kind="serious">检查失败：{check.error}</StatusBadge>
            ) : (
              <>
                <StatusBadge kind={check.allowed ? "good" : "serious"}>
                  {check.allowed ? "允许" : "拒绝"}
                </StatusBadge>
                <span className="text-xs text-text-secondary">
                  {check.action} ← 当前身份 {check.username}
                </span>
              </>
            )}
          </div>
        )}
      </Card>

      {/* 审计事件（append-only，最近 50 条） */}
      <Card title="审计事件" hint="append-only · 最近 50 条">
        <ApiTable
          rows={(audit.data?.events ?? []).slice(0, 50)}
          cols={cols}
          loading={audit.loading}
          error={audit.error}
          onRetry={audit.reload}
          emptyText="暂无审计事件"
          rowKey={(e) => e.audit_id}
        />
      </Card>
    </div>
  );
}

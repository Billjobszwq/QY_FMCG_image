/**
 * SKU 主数据（/master/skus）—— v3 真实数据页面（P6）。
 *
 * 数据源（全部同源 /api/v1/*，无样本数据）：
 * —— GET  /master/skus?include_superseded=true   真实产品库表（含 supersede 链）
 * —— POST master/skus                            新建 SKU
 *
 * 交互纪律：搜索框过滤在客户端完成（列含 sku_id / 名称 / 类目 / 状态等
 * web 所显列）；状态一律 StatusBadge（图标 + 文字）。
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

interface SkuAlias {
  alias: string;
  kind: string;
  customer_id: string | null;
}

interface SkuRow {
  sku_id: string;
  canonical_name: string;
  brand?: string | null;
  category?: string | null;
  volume?: string | null;
  package_version: string;
  superseded_by: string | null;
  valid_from: string | null;
  valid_to: string | null;
  status: string;
  aliases: SkuAlias[];
}

interface ActionMsg {
  ok: boolean;
  text: string;
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

/** SKU 状态徽章：active → good，superseded → warn，停用 → serious。 */
function SkuStatus({ status }: { status: string }) {
  if (status === "active") return <StatusBadge kind="good">在售</StatusBadge>;
  if (status === "superseded") return <StatusBadge kind="warn">已被替代</StatusBadge>;
  if (status === "inactive" || status === "retired") {
    return <StatusBadge kind="serious">停用</StatusBadge>;
  }
  return <StatusBadge kind="neutral">{status}</StatusBadge>;
}

/** 别名 / 客户显示名 展示（与 web 格式一致）。 */
function AliasCell({ aliases }: { aliases: SkuAlias[] }) {
  if (!aliases || aliases.length === 0) {
    return <span className="text-text-secondary">—</span>;
  }
  return (
    <span className="text-[11px] text-text-secondary">
      {aliases
        .map(
          (a) =>
            `${a.alias}（${a.kind === "customer_display_name" ? `客户 ${a.customer_id ?? ""}` : "别名"}）`,
        )
        .join("、")}
    </span>
  );
}

/* ============================================================================
   页面
   ========================================================================== */

export default function SkusPage() {
  const skus = useApi<{ skus: SkuRow[] }>(
    () => fetchIamGet("/master/skus?include_superseded=true"),
    [],
  );

  // ---- 新建 SKU 表单 ----
  const [form, setForm] = useState({
    sku_id: "",
    canonical_name: "",
    brand: "",
    category: "",
    volume: "",
    barcode: "",
    package_version: "v1",
    valid_from: "",
    valid_to: "",
  });
  const [msg, setMsg] = useState<ActionMsg | null>(null);

  // ---- 客户端搜索过滤 ----
  const [q, setQ] = useState("");

  async function createSku() {
    setMsg(null);
    try {
      await fetchIamPost("master/skus", form);
      setMsg({ ok: true, text: "创建成功" });
      skus.reload();
    } catch (e) {
      setMsg({ ok: false, text: `创建失败：${errorMessageOf(e)}` });
    }
  }

  if (isNeedLogin(skus.error)) {
    return (
      <div className="p-5 space-y-4">
        <PageHeader title="SKU 主数据" desc="共享主数据：别名 / 有效期 / supersede 链" />
        <NeedLoginState onOpenLogin={openLoginWindow} />
      </div>
    );
  }

  const lower = q.trim().toLowerCase();
  const hit = (skus.data?.skus ?? []).filter((s) => {
    if (!lower) return true;
    return (
      s.sku_id.toLowerCase().includes(lower) ||
      s.canonical_name.toLowerCase().includes(lower) ||
      (s.brand ?? "").toLowerCase().includes(lower) ||
      (s.category ?? "").toLowerCase().includes(lower) ||
      (s.aliases ?? []).some((a) => a.alias.toLowerCase().includes(lower))
    );
  });

  const cols: ApiTableCol<SkuRow>[] = [
    { key: "sku_id", label: "sku_id" },
    { key: "canonical_name", label: "名称" },
    {
      key: "category",
      label: "类目",
      render: (s) =>
        s.category || s.brand ? (
          <span>
            {s.category || "—"}
            {s.brand && <span className="text-xs text-text-secondary"> · {s.brand}</span>}
          </span>
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
    {
      key: "package_version",
      label: "包装",
      render: (s) =>
        s.superseded_by ? `${s.package_version} → ${s.superseded_by}` : s.package_version,
    },
    {
      key: "valid_from",
      label: "有效期",
      render: (s) => (
        <span className="text-xs text-text-secondary tabular-nums">
          {s.valid_from || "—"} ~ {s.valid_to || "长期"}
        </span>
      ),
    },
    { key: "status", label: "状态", render: (s) => <SkuStatus status={s.status} /> },
    { key: "aliases", label: "别名 / 显示名", render: (s) => <AliasCell aliases={s.aliases} /> },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="SKU 主数据"
        desc="共享主数据：别名 / 客户显示名 / 有效期 / 新旧包装 supersede 链"
      />

      {/* 新建 SKU */}
      <Card title="新建 SKU">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="SKU ID"
            placeholder="sku_id"
            className="w-32"
            value={form.sku_id}
            onChange={(e) => setForm({ ...form, sku_id: e.target.value })}
          />
          <Input
            aria-label="规范名"
            placeholder="canonical_name"
            className="w-44"
            value={form.canonical_name}
            onChange={(e) => setForm({ ...form, canonical_name: e.target.value })}
          />
          <Input
            aria-label="品牌"
            placeholder="品牌"
            className="w-28"
            value={form.brand}
            onChange={(e) => setForm({ ...form, brand: e.target.value })}
          />
          <Input
            aria-label="类目"
            placeholder="类目"
            className="w-28"
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
          />
          <Input
            aria-label="容量"
            placeholder="容量"
            className="w-24"
            value={form.volume}
            onChange={(e) => setForm({ ...form, volume: e.target.value })}
          />
          <Input
            aria-label="条码"
            placeholder="条码"
            className="w-32"
            value={form.barcode}
            onChange={(e) => setForm({ ...form, barcode: e.target.value })}
          />
          <Input
            aria-label="包装版本"
            placeholder="包装版本 v1/v2"
            className="w-32"
            value={form.package_version}
            onChange={(e) => setForm({ ...form, package_version: e.target.value })}
          />
          <Button
            size="sm"
            disabled={!form.sku_id || !form.canonical_name}
            onClick={() => void createSku()}
          >
            创建
          </Button>
          {msg && <StatusBadge kind={msg.ok ? "good" : "serious"}>{msg.text}</StatusBadge>}
        </div>
      </Card>

      {/* 产品库表（客户端搜索过滤） */}
      <Card title="产品库" hint="含已替代（superseded）SKU">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Input
            aria-label="搜索 SKU"
            placeholder="搜索 sku_id / 名称 / 品牌 / 类目 / 别名"
            className="w-72"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="text-xs text-text-secondary tabular-nums">共 {hit.length} 条</span>
        </div>
        <ApiTable
          rows={hit}
          cols={cols}
          loading={skus.loading}
          error={skus.error}
          onRetry={skus.reload}
          emptyText={q ? "尚无匹配的 SKU" : "暂无 SKU"}
          rowKey={(s) => s.sku_id}
        />
      </Card>
    </div>
  );
}

/**
 * 资产台账（P4）：真实照片资产的追加式不可变台账。
 *
 * 数据源（同源 /api/v1/*，src/lib/api.ts）：
 * —— fetchAssetsSummary(): GET /api/v1/assets/summary → 汇总 KV；
 * —— fetchAssetsList():    GET /api/v1/assets?source_id&limit&offset → 分页明细。
 *
 * 自 web/src/pages/Assets.tsx 瘦版重实现：保留“汇总 + 用途分布 +
 * 来源筛选 + 分页明细”；金标准与审核闭环拆至「质量金标准」页。
 * 口径纪律：SHA 唯一数才是唯一照片数，禁止把目录数量相加冒充唯一总数。
 */
import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchAssetsList, fetchAssetsSummary } from "@/lib/api";
import type { AssetRow, AssetsSummary } from "@/lib/api";
import { useAuth } from "@/store/auth";
import { useWindowManager } from "@/store/windowStore";
import LoginWindow from "@/components/ui/LoginWindow";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import {
  ApiTable,
  ErrorState,
  KV,
  NeedLoginState,
  PageHeader,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";

/** 每页行数（与旧版一致）。 */
const PAGE_SIZE = 50;

/** 用途 → 中文（web 端原样保留）。 */
const PURPOSE_CN: Record<string, string> = {
  detector_training: "Detector 训练候选",
  classifier_retrieval: "分类/检索",
  packaging_unknown_sku: "包装版本/未知 SKU",
  quality_negative: "质量负样本",
  eval_frozen: "评估冻结集",
  to_label: "待标注",
  rejection_evidence: "拒绝证据",
};

/** 打开登录窗口（桌面层窗口管理器全局单例，幂等 id）。 */
function openLoginWindow(): void {
  const wm = useWindowManager.getState();
  wm.openWindow({
    id: "login",
    title: "平台登录",
    content: (
      <LoginWindow
        onLoggedIn={() => useWindowManager.getState().closeWindow("login")}
      />
    ),
    defaultPosition: { x: 160, y: 120 },
    defaultSize: { width: 360, height: 320 },
    resizable: false,
  });
}

/** 用途中文名（未知用途回退原始键，绝不吞数据）。 */
function purposeCn(p: string): string {
  return PURPOSE_CN[p] ?? p;
}

export default function Assets() {
  const me = useAuth((s) => s.me);
  const [summary, setSummary] = useState<AssetsSummary | null>(null);
  const [rows, setRows] = useState<AssetRow[]>([]);
  const [count, setCount] = useState(0);
  const [sourceId, setSourceId] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, list] = await Promise.all([
        fetchAssetsSummary(),
        fetchAssetsList({
          source_id: sourceId || undefined,
          limit: PAGE_SIZE,
          offset,
        }),
      ]);
      setSummary(s);
      setRows(list.items);
      setCount(list.count);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [sourceId, offset]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /* 401 → 需要登录；登录成功（me 变化）后自动重试 */
  const unauthorized = error instanceof ApiError && error.status === 401;
  useEffect(() => {
    if (me && unauthorized) void reload();
  }, [me, unauthorized, reload]);

  const purposeRows = summary
    ? Object.entries(summary.purposes).map(([purpose, n]) => ({
        purpose,
        n,
      }))
    : [];

  const cols: ApiTableCol<AssetRow>[] = [
    { key: "source_id", label: "来源" },
    {
      key: "source_uri",
      label: "引用",
      render: (r) => (
        <span className="block max-w-[300px] truncate" title={r.source_uri}>
          {r.source_uri || "—"}
        </span>
      ),
    },
    { key: "photo_id", label: "photo" },
    {
      key: "sha256",
      label: "SHA",
      render: (r) => (
        <span className="whitespace-nowrap" title={r.sha256}>
          {r.sha256.slice(0, 12)}…
        </span>
      ),
    },
    {
      key: "purposes",
      label: "用途",
      render: (r) =>
        r.purposes.length > 0 ? (
          r.purposes.map(purposeCn).join("、")
        ) : (
          <span className="text-text-secondary">—</span>
        ),
    },
    {
      key: "registered_at",
      label: "登记时间",
      render: (r) => (r.registered_at ? r.registered_at.slice(0, 19).replace("T", " ") : "—"),
    },
  ];

  const purposeCols: ApiTableCol<{ purpose: string; n: number }>[] = [
    {
      key: "purpose",
      label: "用途",
      render: (r) => purposeCn(r.purpose),
    },
    {
      key: "n",
      label: "引用数",
      align: "right",
      render: (r) => r.n.toLocaleString("zh-CN"),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="资产台账"
        desc="追加式不可变台账（source_asset_inventory_v1）；SHA 唯一数才是唯一照片数，禁止把目录数量相加冒充唯一总数"
        aside={
          <Button
            variant="secondary"
            size="sm"
            disabled={loading}
            onClick={() => void reload()}
          >
            刷新
          </Button>
        }
      />

      {unauthorized ? (
        <NeedLoginState onOpenLogin={openLoginWindow} />
      ) : error ? (
        <ErrorState
          message={errorMessageOf(error)}
          onRetry={() => void reload()}
        />
      ) : (
        <>
          {summary && (
            <div className="grid gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <KV
                items={[
                  {
                    label: "来源引用总数",
                    value: `${summary.total_refs.toLocaleString("zh-CN")}（含重复）`,
                  },
                  {
                    label: "SHA 唯一照片数",
                    value: summary.unique_sha.toLocaleString("zh-CN"),
                  },
                  {
                    label: "精确重复组",
                    value: summary.exact_dup_groups.toLocaleString("zh-CN"),
                  },
                  {
                    label: "无 SHA 行",
                    value: summary.rows_without_sha.toLocaleString("zh-CN"),
                  },
                  {
                    label: "无用途行",
                    value: summary.rows_without_purpose.toLocaleString("zh-CN"),
                  },
                  {
                    label: "冻结→训练泄漏",
                    value: summary.leak_frozen_into_training.toLocaleString("zh-CN"),
                  },
                  {
                    label: "台账约束",
                    value: summary.immutable
                      ? "追加式不可变（source_asset_inventory_v1）"
                      : "可变台账",
                  },
                  ...(summary.note
                    ? [{ label: "备注", value: summary.note }]
                    : []),
                ]}
              />
              <div className="min-w-0 space-y-1.5">
                <h2 className="text-xs text-text-secondary">用途分布</h2>
                <ApiTable
                  rows={purposeRows}
                  cols={purposeCols}
                  loading={loading}
                  rowKey={(r) => r.purpose}
                  emptyText="暂无用途记录"
                />
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-text-secondary">来源筛选</span>
            <Select
              aria-label="来源筛选"
              className="w-56"
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">全部来源</option>
              {(summary?.sources ?? []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <span className="text-xs text-text-secondary">
              共 {count.toLocaleString("zh-CN")} 条
            </span>
          </div>

          <ApiTable
            rows={rows}
            cols={cols}
            loading={loading}
            rowKey={(r) => r.asset_id}
            emptyText="当前来源暂无资产登记"
          />

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={offset <= 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              上一页
            </Button>
            <span className="text-xs text-text-secondary">
              {count === 0
                ? "0"
                : `${offset + 1}–${Math.min(offset + PAGE_SIZE, count)}`}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={offset + PAGE_SIZE >= count || loading}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              下一页
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

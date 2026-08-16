/**
 * 数据集管理（/vision/datasets）—— 标注批次台账（M4）。
 *
 * 数据源（同源 /api/v1/*，禁样本数据）：
 * —— GET  /labeling/batches：批次列表（assisted / blind 双项目）；
 * —— GET  /labeling/inbox：Label Studio webhook 收件箱事件计数；
 * —— POST /labeling/batches：新建双项目批次（登录 + CSRF）；
 * —— POST /labeling/batches/{id}/import：导入照片并写预标注
 *    （风险操作：触发真实识别预标注，可能耗时数十秒，UI 已标注）；
 * —— GET  /labeling/batches/{id}/reconcile：对账报告（以 LS 为事实源，
 *    不一致显式标记，不谎报）。
 *
 * 状态纪律：loading=HedgehogLoader；错误=ErrorState+重试；
 * 401=NeedLoginState；状态一律 StatusBadge（图标+文字）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  fetchCreateLabelingBatch,
  fetchImportLabelingFiles,
  fetchLabelingBatches,
  fetchLabelingInbox,
  fetchLabelingReconcile,
} from "@/lib/api";
import type { LabelingBatch, ReconcileProject, ReconcileReport } from "@/lib/api";
import {
  ApiTable,
  ErrorState,
  NeedLoginState,
  PageHeader,
  StatusBadge,
  errorMessageOf,
} from "@/components/data";
import type { ApiTableCol } from "@/components/data";
import { StatTile } from "@/components/charts/primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { HedgehogLoader } from "@/components/ui/loader";
import LoginWindow from "@/components/ui/LoginWindow";
import { getWindowManager } from "@/store/windowStore";

/** 打开登录窗口（幂等：已存在则置前；登录成功后自动关闭）。 */
function openLoginWindow() {
  getWindowManager().openWindow({
    id: "login",
    title: "平台登录",
    content: (
      <LoginWindow onLoggedIn={() => getWindowManager().closeWindow("login")} />
    ),
    defaultPosition: { x: 160, y: 120 },
    defaultSize: { width: 352, height: 420 },
    resizable: false,
  });
}

/** 批次状态 → StatusBadge（reconciled/closed 为完成态）。 */
const BATCH_STATUS_CN: Record<string, string> = {
  open: "进行中",
  importing: "导入中",
  reconciled: "已对账",
  closed: "已关闭",
};

function BatchStatusBadge({ status }: { status: string }) {
  const kind = status === "reconciled" || status === "closed" ? "good" : "neutral";
  return <StatusBadge kind={kind}>{BATCH_STATUS_CN[status] ?? status}</StatusBadge>;
}

/** 对账报告行（assisted / blind 两个项目）。 */
interface ReconcileRow extends ReconcileProject {
  project: string;
}

const RECONCILE_COLS: ApiTableCol<ReconcileRow>[] = [
  { key: "project", label: "项目" },
  { key: "project_id", label: "项目 ID", align: "right" },
  { key: "tasks", label: "tasks", align: "right" },
  { key: "annotations_api", label: "标注(API)", align: "right" },
  { key: "predictions_api", label: "预测(API)", align: "right" },
  { key: "inbox_events", label: "inbox 事件", align: "right" },
  { key: "inbox_annotation_events", label: "inbox 标注", align: "right" },
  {
    key: "consistent",
    label: "一致",
    render: (r) => (
      <StatusBadge kind={r.consistent ? "good" : "serious"}>
        {r.consistent ? "一致" : "不一致"}
      </StatusBadge>
    ),
  },
];

export default function Datasets() {
  // ---- 批次列表 / inbox（页面主数据） ----
  const [batches, setBatches] = useState<LabelingBatch[] | null>(null);
  const [inbox, setInbox] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needLogin, setNeedLogin] = useState(false);

  // ---- 对账报告 ----
  const [reconcile, setReconcile] = useState<ReconcileReport | null>(null);

  // ---- 操作区（新建 / 导入） ----
  const [name, setName] = useState("");
  const [targetBatch, setTargetBatch] = useState("");
  const [fileCount, setFileCount] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNeedLogin(false);
    try {
      const [b, i] = await Promise.all([
        fetchLabelingBatches(),
        fetchLabelingInbox().catch(() => null),
      ]);
      setBatches(b.batches);
      setInbox(i ? i.count : null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setError(errorMessageOf(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  /** 操作统一包裹：锁定 busy、提取错误文案、401 转“需要登录”。 */
  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setActionErr(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setNeedLogin(true);
      else setActionErr(errorMessageOf(e));
    } finally {
      setBusy(null);
    }
  };

  const onReconcile = (batchId: string) =>
    act(`reconcile:${batchId}`, async () => {
      setReconcile(await fetchLabelingReconcile(batchId));
    });

  const onCreate = () =>
    act("create", async () => {
      const out = await fetchCreateLabelingBatch(name.trim());
      setName("");
      setTargetBatch(out.batch.batch_id);
      await reload();
    });

  const onImport = () =>
    act("import", async () => {
      const files = Array.from(fileRef.current?.files ?? []);
      if (!targetBatch || files.length === 0) return;
      const report = await fetchImportLabelingFiles(targetBatch, files);
      if (fileRef.current) fileRef.current.value = "";
      setFileCount(0);
      setImportMsg(
        `导入完成：assisted ${JSON.stringify(report["assisted"])} / blind ${JSON.stringify(
          report["blind"],
        )} / 写入预标注 ${String(report["predictions_written"])}`,
      );
      await reload();
      setReconcile(await fetchLabelingReconcile(targetBatch));
    });

  const batchCols: ApiTableCol<LabelingBatch>[] = [
    { key: "name", label: "批次" },
    {
      key: "batch_id",
      label: "batch_id",
      render: (b) => (
        <span className="text-text-secondary">{b.batch_id.slice(0, 8)}…</span>
      ),
    },
    {
      key: "assisted_project_id",
      label: "assisted 项目",
      align: "right",
      render: (b) =>
        b.assisted_project_id === null ? (
          <span className="text-text-secondary">—</span>
        ) : (
          `#${b.assisted_project_id} 辅助标注`
        ),
    },
    {
      key: "blind_project_id",
      label: "blind 项目",
      align: "right",
      render: (b) =>
        b.blind_project_id === null ? (
          <span className="text-text-secondary">—</span>
        ) : (
          `#${b.blind_project_id} 盲审`
        ),
    },
    { key: "task_count", label: "任务数", align: "right" },
    { key: "status", label: "状态", render: (b) => <BatchStatusBadge status={b.status} /> },
    { key: "created_at", label: "创建时间" },
    {
      key: "actions",
      label: "操作",
      render: (b) => (
        <Button
          variant="secondary"
          size="sm"
          disabled={busy !== null}
          onClick={() => onReconcile(b.batch_id)}
        >
          {busy === `reconcile:${b.batch_id}` ? "对账中…" : "对账"}
        </Button>
      ),
    },
  ];

  return (
    <div className="p-5 space-y-4">
      <PageHeader
        title="数据集管理"
        desc="标注批次台账：assisted / blind 双项目，导入与对账以 Label Studio 为事实源"
        aside={
          <Button variant="secondary" size="sm" onClick={reload} disabled={loading}>
            刷新
          </Button>
        }
      />

      {needLogin ? (
        <NeedLoginState onOpenLogin={openLoginWindow} />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        <>
          {/* 台账计数（真实接口返回，不硬编码） */}
          <div className="grid max-w-md grid-cols-2 gap-3">
            <StatTile label="批次总数" value={batches?.length ?? 0} />
            <StatTile
              label="webhook 收件箱"
              value={inbox === null ? "—" : inbox}
              note="按 (source, event_id) 去重"
            />
          </div>

          <ApiTable<LabelingBatch>
            rows={batches ?? []}
            cols={batchCols}
            loading={loading && batches === null}
            emptyText="暂无批次：创建双项目批次并导入照片开始标注"
            rowKey={(b) => b.batch_id}
          />

          {/* 对账报告（点击行内“对账”后出现） */}
          {reconcile && (
            <section className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-display text-sm font-bold text-text-primary">
                  对账报告 · {reconcile.batch_id.slice(0, 8)}…
                </h2>
                <StatusBadge kind={reconcile.consistent ? "good" : "serious"}>
                  {reconcile.consistent ? "consistent" : "inconsistent（显式标记，不谎报）"}
                </StatusBadge>
                <StatusBadge kind={reconcile.blind_no_predictions ? "good" : "serious"}>
                  {reconcile.blind_no_predictions
                    ? "blind 0 prediction 成立"
                    : "blind 出现 prediction（违背设计）"}
                </StatusBadge>
              </div>
              <ApiTable<ReconcileRow>
                rows={[
                  { project: "assisted", ...reconcile.projects.assisted },
                  { project: "blind", ...reconcile.projects.blind },
                ]}
                cols={RECONCILE_COLS}
                rowKey={(r) => r.project}
              />
            </section>
          )}

          {/* 新建批次 / 导入照片（写操作需登录会话，自动携带 CSRF） */}
          <section className="space-y-2 rounded-md border border-border bg-surface p-3">
            <h2 className="font-display text-sm font-bold text-text-primary">
              新建批次 / 导入照片
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                className="w-48"
                placeholder="批次名（如 trial10）"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && name.trim() && busy === null) onCreate();
                }}
              />
              <Button size="sm" disabled={busy !== null || !name.trim()} onClick={onCreate}>
                {busy === "create" ? "创建中…" : "创建双项目批次"}
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                className="w-60"
                value={targetBatch}
                onChange={(e) => setTargetBatch(e.target.value)}
                aria-label="选择目标批次"
              >
                <option value="">选择目标批次…</option>
                {(batches ?? []).map((b) => (
                  <option key={b.batch_id} value={b.batch_id}>
                    {b.name}（{b.batch_id.slice(0, 8)}…）
                  </option>
                ))}
              </Select>
              <input
                ref={fileRef}
                type="file"
                multiple
                accept="image/*"
                className="hidden"
                onChange={(e) => setFileCount(e.target.files?.length ?? 0)}
              />
              <Button
                variant="secondary"
                size="sm"
                disabled={busy !== null || !targetBatch}
                onClick={() => fileRef.current?.click()}
              >
                选择照片{fileCount > 0 ? `（已选 ${fileCount} 张）` : ""}
              </Button>
              <Button
                size="sm"
                disabled={busy !== null || !targetBatch || fileCount === 0}
                onClick={onImport}
              >
                {busy === "import" ? "导入中…" : "导入并写预标注"}
              </Button>
            </div>

            {importMsg && <p className="text-xs text-text-secondary">{importMsg}</p>}
            {actionErr && (
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge kind="serious">操作失败</StatusBadge>
                <span className="text-xs text-text-secondary">{actionErr}</span>
              </div>
            )}
            <p className="text-xs text-text-secondary">
              风险说明：导入会触发真实识别预标注（可能耗时数十秒）；blind
              项目绝不写入 prediction（对账 blind_no_predictions 校验）；平台不自动启动任何训练。
            </p>
          </section>

          {/* 二次刷新期间给一个轻量加载提示（数据保留在表格中） */}
          {loading && batches !== null && (
            <div className="flex justify-center">
              <HedgehogLoader className="h-7 w-auto" />
            </div>
          )}
        </>
      )}
    </div>
  );
}

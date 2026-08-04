import { useCallback, useEffect, useState } from "react";
import {
  RecognitionResult,
  RecognitionTaskRow,
  RecognitionTaskView,
  fetchRecognitionTasks,
  recognizeByUrl,
  recognizeFile,
  uploadRecognitionFiles,
} from "../api";

const ENTRY_CN: Record<string, string> = {
  single_file: "单文件",
  batch_file: "批量文件",
  url: "URL",
  api: "API",
};

export default function Recognition() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecognitionResult | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [preview, setPreview] = useState<string | null>(null);
  const [taskView, setTaskView] = useState<RecognitionTaskView | null>(null);
  const [url, setUrl] = useState("");
  const [tasks, setTasks] = useState<RecognitionTaskRow[] | null>(null);

  const reloadTasks = useCallback(async () => {
    try {
      const d = await fetchRecognitionTasks();
      setTasks(d.tasks);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    reloadTasks();
  }, [reloadTasks]);

  const onFile = async (f: File | null) => {
    if (!f) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setTaskView(null);
    setFileName(f.name);
    setPreview(URL.createObjectURL(f));
    try {
      setResult(await recognizeFile(f));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onBatch = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    setTaskView(null);
    try {
      setTaskView(await uploadRecognitionFiles(Array.from(files)));
      await reloadTasks();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onUrl = async () => {
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    setTaskView(null);
    try {
      setTaskView(await recognizeByUrl(url.trim()));
      await reloadTasks();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2>图片识别（统一入口）</h2>
      <p className="muted">
        单文件 / 批量文件 / URL 共用同一识别服务层（8091 级联识别，bundle
        prod_20260804_v4_r2），任务写入统一历史。写操作需登录。
      </p>
      {busy && <p className="muted">识别中…</p>}
      {error && <div className="banner banner-unavailable">识别失败：{error}</div>}

      <h3>① 单文件识别（即时结果，不计任务历史）</h3>
      <label className="upload">
        <input type="file" accept="image/*" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        选择照片上传识别
      </label>
      {preview && result && (
        <div className="rec-grid">
          <img src={preview} alt={fileName} className="rec-img" />
          <div>
            <p>
              <b>{fileName}</b> · run_id <code>{result.run_id}</code>
            </p>
            <p className="muted">
              上游耗时 {result.elapsed_ms} ms · bridge 耗时 {result.bridge_elapsed_ms} ms · 模型{" "}
              {result.model}
            </p>
            {result.count === 0 ? (
              <div className="note">未检出商品（0 个）。近景/非货架图或不在 208 类 registry 内的商品会 fail-closed 返回 0。</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>名称</th>
                    <th>置信度</th>
                    <th>needs_review</th>
                  </tr>
                </thead>
                <tbody>
                  {result.products.map((p, i) => (
                    <tr key={i}>
                      <td>{p.sku_id || "—"}</td>
                      <td>{p.name}</td>
                      <td>{(p.confidence * 100).toFixed(1)}%</td>
                      <td>{p.needs_review ? "是" : "否"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <h3>② 批量文件识别（计入任务历史，需登录）</h3>
      <label className="upload">
        <input
          type="file"
          accept="image/*"
          multiple
          onChange={(e) => onBatch(e.target.files)}
        />
        选择多张照片批量识别
      </label>

      <h3>③ URL 识别（计入任务历史，需登录）</h3>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          placeholder="http(s)://…/photo.jpg"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onUrl()}
          style={{ flex: 1 }}
        />
        <button onClick={onUrl} disabled={busy}>
          识别
        </button>
      </div>

      {taskView && (
        <div style={{ marginTop: 12 }}>
          <p>
            <span className="pill pill-healthy">{ENTRY_CN[taskView.task.entry] ?? taskView.task.entry}</span>{" "}
            共 {taskView.task.file_count} 个输入 · 检出 {taskView.task.sku_count} 个商品 · 耗时{" "}
            {taskView.elapsed_ms} ms
          </p>
          {taskView.errors.length > 0 && (
            <div className="banner banner-degraded">
              {taskView.errors.map((e) => (
                <p key={e} style={{ margin: "2px 0" }}>{e}</p>
              ))}
            </div>
          )}
          <table>
            <thead>
              <tr>
                <th>输入</th>
                <th>检出数</th>
                <th>模型</th>
              </tr>
            </thead>
            <tbody>
              {taskView.results.map((r, i) => (
                <tr key={i}>
                  <td>{String(r.name ?? "?")}</td>
                  <td>{String(r.count ?? 0)}</td>
                  <td className="muted">{String(r.model ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>④ 识别任务历史（四入口统一）</h3>
      {tasks === null ? (
        <p className="muted">加载中…</p>
      ) : tasks.length === 0 ? (
        <p className="muted">暂无任务。批量/URL/API/Agent 识别都会记录在此。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>入口</th>
              <th>状态</th>
              <th>输入数</th>
              <th>检出商品</th>
              <th>发起人</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {tasks.slice(0, 30).map((t) => (
              <tr key={t.task_id}>
                <td>{ENTRY_CN[t.entry] ?? t.entry}</td>
                <td>
                  <span className={`pill pill-${t.status === "completed" ? "healthy" : "unavailable"}`}>
                    {t.status}
                  </span>
                </td>
                <td>{t.file_count}</td>
                <td>{t.sku_count}</td>
                <td>{t.created_by}</td>
                <td className="muted">{t.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

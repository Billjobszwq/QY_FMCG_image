import { useState } from "react";
import { RecognitionResult, recognizeFile } from "../api";

export default function Recognition() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecognitionResult | null>(null);
  const [fileName, setFileName] = useState<string>("");
  const [preview, setPreview] = useState<string | null>(null);

  const onFile = async (f: File | null) => {
    if (!f) return;
    setBusy(true);
    setError(null);
    setResult(null);
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

  return (
    <section>
      <h2>图片识别</h2>
      <p className="muted">
        上传照片经统一 API（8400）转发至 legacy.recognition.v2（8091 级联识别，bundle
        prod_20260804_v4_r2）。第一阶段不切换生产入口。
      </p>
      <label className="upload">
        <input type="file" accept="image/*" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        选择照片上传识别
      </label>
      {busy && <p className="muted">识别中…</p>}
      {error && <div className="banner banner-unavailable">识别失败：{error}</div>}
      {preview && (
        <div className="rec-grid">
          <img src={preview} alt={fileName} className="rec-img" />
          <div>
            {result && (
              <>
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
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

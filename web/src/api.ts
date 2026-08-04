export type HealthStatus = "healthy" | "degraded" | "unavailable";

export interface ServiceStatus {
  name: string;
  status: HealthStatus;
  latency_ms: number | null;
  detail: string | null;
  critical: boolean;
  description: string;
}

export interface HealthBody {
  status: HealthStatus;
  generated_at: string;
  services: ServiceStatus[];
}

export interface RecognitionProduct {
  box: number[];
  sku_id: string;
  name: string;
  confidence: number;
  margin: number | null;
  yolo_name: string | null;
  yolo_confidence: number | null;
  source: string;
  needs_review: boolean;
}

export interface RecognitionResult {
  capability: string;
  run_id: string;
  products: RecognitionProduct[];
  count: number;
  elapsed_ms: number;
  bridge_elapsed_ms: number;
  model: string;
}

export async function fetchHealth(): Promise<HealthBody> {
  const r = await fetch("/api/v1/health");
  if (!r.ok) throw new Error(`health HTTP ${r.status}`);
  return r.json();
}

export async function fetchVersion(): Promise<{ platform: string; version: string }> {
  const r = await fetch("/api/v1/version");
  return r.json();
}

export async function fetchMonitorLive(): Promise<Record<string, unknown>> {
  const r = await fetch("/api/v1/monitor/live");
  if (!r.ok) throw new Error(`monitor HTTP ${r.status}`);
  return r.json();
}

export async function fetchMonitorOverview(): Promise<Record<string, unknown>> {
  const r = await fetch("/api/v1/monitor/overview");
  if (!r.ok) throw new Error(`monitor HTTP ${r.status}`);
  return r.json();
}

export async function recognizeFile(file: File, conf = 0.25): Promise<RecognitionResult> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/v1/recognition/recognize?conf=${conf}`, {
    method: "POST",
    body: form,
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      detail = `${body.error ?? "error"}: ${body.detail ?? ""}`;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return r.json();
}

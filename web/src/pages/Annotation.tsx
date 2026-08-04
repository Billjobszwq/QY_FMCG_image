import { HealthBody } from "../api";

export default function Annotation({ health }: { health: HealthBody | null }) {
  const ls = health?.services.find((s) => s.name === "label_studio");
  const up = ls?.status === "healthy";
  return (
    <section>
      <h2>标注审核</h2>
      {!health && <p className="muted">正在加载…</p>}
      {health && !up && (
        <div className="banner banner-degraded">
          Label Studio（8300）当前不可用（{ls?.detail ?? "unavailable"}）。
          标注审核以 degraded 显示；M4 将修复 start_label_studio.sh 路径并恢复闭环。
        </div>
      )}
      {up && (
        <p>
          Label Studio 可用：<a href="http://127.0.0.1:8300" target="_blank" rel="noreferrer">打开 8300</a>
        </p>
      )}
      <p className="muted">
        SAM 辅助重标注队列（250 项 pending，双审 200 / 盲抽 50）处于 awaiting_human_review，
        等待人工双审授权后继续；新平台不自动启动任何训练。
      </p>
    </section>
  );
}

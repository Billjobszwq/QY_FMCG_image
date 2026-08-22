// 统一模型管理 V1（M9）：旧 web 树的诚实指引页。
// 模型管理的完整交互（连接/目录/绑定/治理）位于桌面端
// （frontend/ “模型管理”模块）；旧 web 树仅提供说明与本地模型
// 只读内容（/models/local 复用 VisionModels）。不放样本数据。
export function ModelManagementNotice({ tab }: { tab: string }) {
  return (
    <div style={{ padding: 24, maxWidth: 720 }}>
      <h2 style={{ marginBottom: 8 }}>模型管理 · {tab}</h2>
      <p style={{ color: "#555", lineHeight: 1.7 }}>
        该功能已迁移至桌面端“模型管理”模块（连接管理 / 模型目录 /
        能力分配 / 运行治理 / 本地模型）。旧 web 树不再提供模型连接、
        密钥与绑定操作入口；本地模型驻留与训练门禁请使用
        <code> /models/local</code>（原“模型与训练”内容）。
      </p>
      <p style={{ color: "#888", marginTop: 12, fontSize: 12 }}>
        兼容说明：旧路由 /vision/models 已重定向到 /models/local。
      </p>
    </div>
  );
}

export default ModelManagementNotice;

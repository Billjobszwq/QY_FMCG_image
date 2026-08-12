import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8400",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // SI2 T9：vendor 拆分 —— react 核心独立 chunk；重型库随路由
        // lazy chunk 异步加载，不进初始包。
        // SI3 T10（指令 11.2）：echarts/zrender/maplibre 继续拆分：
        // zrender 渲染引擎与 echarts 核心分离，各自 <500KB；
        // maplibre 为单库不可再拆（实测理由与加载预算见
        // scope-integrity-v3/FINAL-REPORT 性能节）。
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("zrender")) return "vendor-zrender";
          if (id.includes("echarts")) return "vendor-echarts";
          if (id.includes("maplibre")) return "vendor-maplibre";
          if (id.includes("node_modules/react/")
            || id.includes("node_modules/react-dom/")
            || id.includes("node_modules/react-router")
            || id.includes("node_modules/@remix-run/")
            || id.includes("node_modules/scheduler/")) {
            return "vendor-react";
          }
          return undefined;
        },
      },
    },
  },
});

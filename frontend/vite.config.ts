import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // dev 同源代理：一切业务数据走 /api/v1/*（后端默认 8400 端口）
    proxy: {
      "/api": "http://127.0.0.1:8400",
      // orchestrator 的 GET 不带 CORS 头，dev 同源代理剥前缀后转 :8304
      "/orchestrator": {
        target: "http://127.0.0.1:8304",
        rewrite: (p) => p.replace(/^\/orchestrator/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});

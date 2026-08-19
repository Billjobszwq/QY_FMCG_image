#!/usr/bin/env node
/* ============================================================================
   TaaS frontend 生产静态服务器（零依赖，仅 node 标准库）

   —— /api/* 反向代理到平台后端 http://127.0.0.1:8400（保留 cookie / 头部，
      与 vite dev 的同源代理等价，CSRF 与会话 cookie 原样透传）；
   —— /health 与 / 返回 200（健康探活路径，见 docs/services.json）；
   —— 其余请求服务构建产物 dist/，未知无扩展名路径 SPA 回退 index.html；
   —— 端口默认 4173，可用 --port=<n> / --port <n> 覆盖。

   用法：
     npm --prefix frontend run build   # 先构建出 dist/
     node frontend/server/serve.mjs    # 或 --port 4173
   ========================================================================== */
import { createServer, request as upstreamRequest } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
/** 构建产物目录（npm run build 输出）。 */
const DIST_DIR = path.resolve(__dirname, "..", "dist");
/** 平台后端（/api/v1/* 同源代理目标）。 */
const BACKEND_HOST = "127.0.0.1";
/** orchestrator 端口（照片库/直连识别；其 GET 不带 CORS 头，须同源代理）。 */
const ORCH_PORT = 8304;
const BACKEND_PORT = 8400;

/** 解析 --port 参数；缺省 4173。 */
function parsePort(argv) {
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--port") {
      const v = Number(argv[i + 1]);
      if (Number.isInteger(v) && v > 0) return v;
    } else if (arg.startsWith("--port=")) {
      const v = Number(arg.slice("--port=".length));
      if (Number.isInteger(v) && v > 0) return v;
    }
  }
  return 4173;
}

/** 静态文件 Content-Type（覆盖 dist 全部产物类型）。 */
const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".txt": "text/plain; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
};

function contentTypeOf(filePath) {
  return MIME_TYPES[path.extname(filePath).toLowerCase()] ?? "application/octet-stream";
}

/** /api/* → 反向代理到平台后端：方法 / 路径 / 头部（含 cookie）原样透传。 */
function proxyToBackend(req, res) {
  const headers = { ...req.headers, host: `${BACKEND_HOST}:${BACKEND_PORT}` };
  const upstream = upstreamRequest(
    {
      host: BACKEND_HOST,
      port: BACKEND_PORT,
      method: req.method,
      path: req.url,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", (err) => {
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    }
    res.end(
      JSON.stringify({
        error: "bad_gateway",
        detail: `平台后端（${BACKEND_HOST}:${BACKEND_PORT}）不可达：${err.message}`,
      }),
    );
  });
  req.pipe(upstream);
}

/** /orchestrator/* → orchestrator :8304：剥前缀后透传（其 GET 无 CORS 头，须同源代理）。 */
function proxyToOrchestrator(req, res, pathname, search) {
  const stripped = pathname.replace(/^\/orchestrator/, "") || "/";
  const headers = { ...req.headers, host: `${BACKEND_HOST}:${ORCH_PORT}` };
  const upstream = upstreamRequest(
    {
      host: BACKEND_HOST,
      port: ORCH_PORT,
      method: req.method,
      path: stripped + search,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", (err) => {
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    }
    res.end(
      JSON.stringify({
        error: "bad_gateway",
        detail: `orchestrator（${BACKEND_HOST}:${ORCH_PORT}）不可达：${err.message}`,
      }),
    );
  });
  req.pipe(upstream);
}

/** 发送单个静态文件（index.html 不缓存，其余按 Vite 指纹产物长缓存）。 */
async function sendFile(res, filePath) {
  const body = await readFile(filePath);
  const isIndex = path.basename(filePath) === "index.html";
  res.writeHead(200, {
    "Content-Type": contentTypeOf(filePath),
    "Content-Length": body.length,
    "Cache-Control": isIndex ? "no-cache" : "public, max-age=31536000, immutable",
  });
  res.end(body);
}

/** 静态服务：dist 文件 → 目录 index.html → 无扩展名路径 SPA 回退 → 404。 */
async function serveStatic(req, res, pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("非法路径");
    return;
  }

  // 防目录穿越：规范化后必须仍在 dist/ 之内
  const target = path.normalize(path.join(DIST_DIR, decoded));
  if (target !== DIST_DIR && !target.startsWith(DIST_DIR + path.sep)) {
    res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("禁止访问");
    return;
  }

  try {
    const st = await stat(target);
    if (st.isFile()) {
      await sendFile(res, target);
      return;
    }
    if (st.isDirectory()) {
      await sendFile(res, path.join(target, "index.html"));
      return;
    }
  } catch {
    // 文件不存在 → 走下方 SPA 回退 / 404
  }

  // SPA 回退：仅对无扩展名的路径（客户端路由）回退 index.html
  if (path.extname(decoded) === "") {
    try {
      await sendFile(res, path.join(DIST_DIR, "index.html"));
      return;
    } catch {
      // dist 未构建 → 落到 404 分支给出提示
    }
  }

  res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("未找到该资源；若 dist/ 尚未构建，请先执行 npm --prefix frontend run build");
}

const PORT = parsePort(process.argv.slice(2));

const server = createServer((req, res) => {
  let pathname;
  try {
    pathname = new URL(req.url ?? "/", "http://localhost").pathname;
  } catch {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("非法请求");
    return;
  }

  // /api/*（含 /api/v1/*）→ 平台后端；保留 cookie / 头部
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    proxyToBackend(req, res);
    return;
  }

  // /orchestrator/* → orchestrator :8304（剥前缀；CORS 同源代理）
  if (pathname === "/orchestrator" || pathname.startsWith("/orchestrator/")) {
    proxyToOrchestrator(
      req,
      res,
      pathname,
      new URL(req.url ?? "/", "http://localhost").search,
    );
    return;
  }

  // 健康探活路径
  if (pathname === "/health") {
    res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("ok");
    return;
  }

  // 其余走静态（/ 即 index.html，返回 200，满足健康路径要求）
  void serveStatic(req, res, pathname);
});

server.on("error", (err) => {
  console.error(`[frontend] 启动失败：${err.message}`);
  process.exit(1);
});

server.listen(PORT, () => {
  console.log(
    `[frontend] 静态服务 http://127.0.0.1:${PORT}（dist=${DIST_DIR}），/api/* 代理至 http://${BACKEND_HOST}:${BACKEND_PORT}`,
  );
});

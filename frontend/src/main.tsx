import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
/* 字体自托管（@fontsource，随构建打包，无 CDN 依赖）：
   —— IBM Plex Sans：标题/展示（400/700 两档；IBM Plex Sans 无 800 字重，
     font-extrabold 由浏览器就近映射到 700）
   —— Caveat：手写趣味字体（variable wght 400–700，对应 --font-squeak） */
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource-variable/caveat";
import App from "./App";
import "./styles/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

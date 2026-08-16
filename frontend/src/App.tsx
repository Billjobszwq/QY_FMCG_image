import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import DemoDesktop from "@/pages/DemoDesktop";

/**
 * 路由壳：当前阶段仅一个演示页面。
 * 后续页面（仪表盘 / 文档 / 博客…）在 Routes 中追加即可，
 * 或按需在窗口内直接渲染页面组件。
 *
 * <MotionConfig reducedMotion="user">：尊重系统"减弱动态效果"偏好，
 * Framer Motion 在用户开启 prefers-reduced-motion 时自动停用 transform /
 * layout 动画（保留必要的透明度变化），与 styles/index.css 的
 * @media (prefers-reduced-motion) 规则互补。
 */
export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<DemoDesktop />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  );
}

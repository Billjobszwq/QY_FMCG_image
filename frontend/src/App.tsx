import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import DemoDesktop from "@/pages/DemoDesktop";

/**
 * 路由壳：单页产品桌面（DemoDesktop = Sidebar + 桌面窗口层 + Taskbar）。
 * 模块页面不挂路由，由窗口管理器按 modules/registry 的路由键懒加载进窗口。
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

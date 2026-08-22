/**
 * 兼容 shim（统一模型管理 V1，04 §3.5）：
 * 模型驻留/训练门禁内容已迁移至模型管理模块 `/models/local`。
 * 本文件在兼容期结束前不得删除；旧路由经别名解析到同一组件，
 * 不复制组件状态源。
 */
export { default } from "@/pages/models/LocalModels";

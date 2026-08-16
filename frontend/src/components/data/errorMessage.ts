/**
 * 从 unknown 异常提取可展示文案（ApiError.message / Error.message）。
 * 独立文件：保持 ErrorState.tsx 只导出组件（fast refresh 约束）。
 */
export function errorMessageOf(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "数据拉取出错，请稍后重试";
}

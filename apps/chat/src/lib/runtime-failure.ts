const TOOL_FAILURE_CODES = new Set([
  "reference_resolution_error",
  "validation_error",
  "handler_error",
  "tool_error",
  "execution_timeout",
]);

export function formatToolFailure(code?: string | null): string {
  switch (code) {
    case "reference_resolution_error":
      return "依赖的上一步结果不可用。";
    case "validation_error":
      return "工具参数不符合要求。";
    case "execution_timeout":
      return "数据查询超时。";
    case "handler_error":
    case "tool_error":
      return "数据源查询失败。";
    default:
      return "工具未能完成。";
  }
}

export function isToolFailureCode(code?: string | null): boolean {
  return code != null && TOOL_FAILURE_CODES.has(code);
}

import { describe, expect, it } from "vitest";

import { formatToolFailure, isToolFailureCode } from "./runtime-failure";

describe("runtime failure messages", () => {
  it("maps stable dependency failures to friendly Chinese", () => {
    expect(formatToolFailure("reference_resolution_error")).toBe("依赖的上一步结果不可用。");
    expect(formatToolFailure("validation_error")).toBe("工具参数不符合要求。");
  });

  it("keeps unknown codes safe and generic", () => {
    expect(formatToolFailure("private_trace")).toBe("工具未能完成。");
    expect(isToolFailureCode("handler_error")).toBe(true);
    expect(isToolFailureCode("private_trace")).toBe(false);
  });
});
